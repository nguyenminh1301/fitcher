import re

import pytest

from jobs import apply_log_schema

TABLES = [
    "runs", "events", "llm_calls", "sql_runs", "audit",
    "chat_messages", "feedback", "eval_reports", "example_proposals", "admin_actions",
]
# Tables whose rows are replaced on every change and expire 90 days after their last update.
REPLACED_TABLES = ["conversations", "conversation_groups"]


class FakeClient:
    def __init__(self):
        self.commands = []

    def command(self, sql):
        self.commands.append(sql)


def schema_statements():
    return apply_log_schema.split_statements(apply_log_schema.SCHEMA_FILE.read_text(encoding="utf-8"))


def table_statement(table):
    pattern = re.compile(rf"CREATE TABLE IF NOT EXISTS agent_logs\.{table}\s")
    matches = [s for s in schema_statements() if pattern.match(s)]
    assert len(matches) == 1, f"expected one CREATE TABLE for {table}"
    return matches[0]


def test_split_statements_ignores_comments_and_blank_parts():
    sql = "-- header; with a semicolon\nCREATE X;\n\n  -- note\nCREATE Y\n  (a);\n\n"
    assert apply_log_schema.split_statements(sql) == ["CREATE X", "CREATE Y\n  (a)"]


def test_schema_only_creates_objects_that_do_not_exist():
    statements = schema_statements()
    assert statements[0] == "CREATE DATABASE IF NOT EXISTS agent_logs"
    for statement in statements:
        assert re.match(
            r"CREATE (DATABASE|TABLE|VIEW) IF NOT EXISTS |SYSTEM FLUSH LOGS$|ALTER TABLE \S+ ADD COLUMN IF NOT EXISTS ",
            statement,
        ), statement


def test_chat_messages_columns_added_later_reach_existing_volumes():
    created = table_statement("chat_messages")
    for column in ("turn UInt32", "revision UInt32", "result String", "events String"):
        assert f"    {column}" in created
        assert f"ALTER TABLE agent_logs.chat_messages ADD COLUMN IF NOT EXISTS {column}" in schema_statements()


@pytest.mark.parametrize(("table", "column"), [
    ("llm_calls", "tier LowCardinality(String)"),
    ("eval_reports", "tiers Map(String, String)"),
    ("eval_reports", "regressed Nullable(Bool)"),
])
def test_model_routing_columns_reach_existing_volumes(table, column):
    assert f"    {column}" in table_statement(table)
    assert any(
        statement.startswith(f"ALTER TABLE agent_logs.{table} ADD COLUMN IF NOT EXISTS {column}")
        for statement in schema_statements()
    )


def test_model_tiers_keep_the_latest_change_per_tier():
    statements = apply_log_schema.split_statements(apply_log_schema.SCHEMA_FILES[1].read_text(encoding="utf-8"))
    assert len(statements) == 1
    assert statements[0].startswith("CREATE TABLE IF NOT EXISTS data_meta.model_tiers")
    assert "ENGINE = ReplacingMergeTree(changed_at)\nORDER BY tier" in statements[0]


@pytest.mark.parametrize("table", REPLACED_TABLES)
def test_replaced_tables_keep_the_latest_row_per_user_and_id(table):
    statement = table_statement(table)
    assert "ENGINE = ReplacingMergeTree(updated_at)" in statement
    assert "TTL toDateTime(updated_at) + INTERVAL 90 DAY" in statement


@pytest.mark.parametrize("table", TABLES)
def test_every_table_expires_after_90_days_and_accepts_dedup_tokens(table):
    statement = table_statement(table)
    assert "TTL toDateTime(ts) + INTERVAL 90 DAY" in statement
    assert "non_replicated_deduplication_window" in statement


@pytest.mark.parametrize(
    ("table", "order_by"),
    [
        ("runs", "ORDER BY trace_id"),
        ("events", "ORDER BY (trace_id, ts)"),
        ("llm_calls", "ORDER BY (trace_id, ts)"),
        ("sql_runs", "ORDER BY (trace_id, ts)"),
        ("audit", "ORDER BY (trace_id, ts)"),
        ("chat_messages", "ORDER BY (user_id, ts)"),
        ("feedback", "ORDER BY (user_id, ts)"),
        ("eval_reports", "ORDER BY (pack, ts)"),
        ("example_proposals", "ORDER BY (pack, ts)"),
        ("admin_actions", "ORDER BY (action, ts)"),
        ("conversations", "ORDER BY (user_id, conversation_id)"),
        ("conversation_groups", "ORDER BY (user_id, group_id)"),
    ],
)
def test_table_sort_keys(table, order_by):
    assert f"\n{order_by}\n" in table_statement(table)


def test_trace_view_reads_agent_queries_from_query_log():
    views = [s for s in schema_statements() if s.startswith("CREATE VIEW IF NOT EXISTS agent_logs.trace_query_log")]
    assert len(views) == 1
    assert "FROM system.query_log" in views[0]
    assert "log_comment AS trace_id" in views[0]


def test_query_log_exists_before_the_view_reads_it():
    # A fresh server creates system.query_log at its first log flush; the view cannot be created before.
    statements = schema_statements()
    view = next(i for i, s in enumerate(statements) if s.startswith("CREATE VIEW"))
    assert statements[view - 1] == "SYSTEM FLUSH LOGS"


def test_trace_query_reads_every_trace_source_for_one_parameter():
    sql = (apply_log_schema.SCHEMA_FILE.parents[1] / "queries" / "trace.sql").read_text(encoding="utf-8")
    for source in ("runs FINAL", "events", "llm_calls", "sql_runs", "trace_query_log"):
        assert f"agent_logs.{source}" in sql
    assert sql.count("{trace_id:String}") >= 5
    assert "INCOMPLETE" in sql
    # query_log rows such as the runner's DESCRIBE of an empty result have no sql_runs row, so show their text.
    assert "substring(query, 1, " in sql


def test_runs_keeps_the_latest_row_per_trace():
    assert "ENGINE = ReplacingMergeTree(updated_at)" in table_statement("runs")


def test_apply_schema_runs_each_statement_in_order():
    client = FakeClient()
    count = apply_log_schema.apply_schema(client, "CREATE DATABASE IF NOT EXISTS a;\nCREATE TABLE IF NOT EXISTS a.b (x UInt8);")
    assert count == 2
    assert client.commands == ["CREATE DATABASE IF NOT EXISTS a", "CREATE TABLE IF NOT EXISTS a.b (x UInt8)"]


def test_main_reports_missing_credentials(monkeypatch, capsys):
    monkeypatch.delenv("CLICKHOUSE_ADMIN_USER", raising=False)
    monkeypatch.delenv("CLICKHOUSE_ADMIN_PASSWORD", raising=False)
    assert apply_log_schema.main([]) == 1
    assert "CLICKHOUSE_ADMIN_USER" in capsys.readouterr().err


def test_main_applies_every_schema_file_in_order(monkeypatch, capsys):
    client = FakeClient()
    monkeypatch.setattr(apply_log_schema, "admin_client", lambda: client)
    tiers = apply_log_schema.split_statements(apply_log_schema.SCHEMA_FILES[1].read_text(encoding="utf-8"))
    assert apply_log_schema.main([]) == 0
    assert client.commands == [*schema_statements(), *tiers]
    output = capsys.readouterr().out
    assert f"{len(schema_statements())} statements from 010-agent-logs.sql" in output
    assert "1 statements from 020-model-tiers.sql" in output
