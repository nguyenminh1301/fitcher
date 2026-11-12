import re

import pytest

from app.state.migrate import split_statements
from jobs import migrate

AGENT_LOGS = migrate.CLICKHOUSE_CHANGES_DIR / "0002_agent_logs.sql"
MODEL_TIERS = migrate.CLICKHOUSE_CHANGES_DIR / "0003_model_tiers.sql"
DOCUMENTS = migrate.CLICKHOUSE_CHANGES_DIR / "0004_documents.sql"
TABLES = [
    "runs", "events", "llm_calls", "sql_runs", "audit",
    "chat_messages", "feedback", "eval_reports", "example_proposals", "admin_actions",
]
# Tables whose rows are replaced on every change and expire 90 days after their last update.
REPLACED_TABLES = ["conversations", "conversation_groups"]


def schema_statements():
    return split_statements(AGENT_LOGS.read_text(encoding="utf-8"))


def table_statement(table):
    pattern = re.compile(rf"CREATE TABLE IF NOT EXISTS agent_logs\.{table}\s")
    matches = [s for s in schema_statements() if pattern.match(s)]
    assert len(matches) == 1, f"expected one CREATE TABLE for {table}"
    return matches[0]


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
    statements = split_statements(MODEL_TIERS.read_text(encoding="utf-8"))
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
    sql = (migrate.CLICKHOUSE_CHANGES_DIR.parent / "queries" / "trace.sql").read_text(encoding="utf-8")
    for source in ("runs FINAL", "events", "llm_calls", "sql_runs", "trace_query_log"):
        assert f"agent_logs.{source}" in sql
    assert sql.count("{trace_id:String}") >= 5
    assert "INCOMPLETE" in sql
    # query_log rows such as the runner's DESCRIBE of an empty result have no sql_runs row, so show their text.
    assert "substring(query, 1, " in sql


def test_runs_keeps_the_latest_row_per_trace():
    assert "ENGINE = ReplacingMergeTree(updated_at)" in table_statement("runs")











def test_document_registry_is_applied_to_existing_volumes():
    assert DOCUMENTS.name == "0004_documents.sql"
    statements = split_statements(DOCUMENTS.read_text(encoding="utf-8"))
    assert len(statements) == 1
    statement = statements[0]
    assert statement.startswith("CREATE TABLE IF NOT EXISTS data_meta.documents")
    for column in (
        "id String", "pack LowCardinality(String)", "file_name String", "media_type LowCardinality(String)",
        "size_bytes UInt64", "sha256 String", "uploaded_by String", "allowed_roles Array(String)",
        "status LowCardinality(String)", "error String", "chunk_count UInt32", "blocked_chunks UInt32",
        "uploaded_at DateTime64(3, 'UTC')", "deleted_at Nullable(DateTime64(3, 'UTC'))",
        "updated_at DateTime64(3, 'UTC')",
    ):
        assert f"    {column}" in statement, column
    assert "ENGINE = ReplacingMergeTree(updated_at)\nORDER BY (pack, id)" in statement


@pytest.mark.parametrize("column", ["spec String", "error String", "note String", "confidence Float64"])
def test_proposal_columns_reach_existing_volumes(column):
    assert f"    {column}" in table_statement("example_proposals")
    assert f"ALTER TABLE agent_logs.example_proposals ADD COLUMN IF NOT EXISTS {column}" in schema_statements()
