import re

import pytest

from jobs import apply_log_schema

TABLES = [
    "runs", "events", "llm_calls", "sql_runs", "audit",
    "chat_messages", "feedback", "eval_reports", "example_proposals",
]


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
        assert re.match(r"CREATE (DATABASE|TABLE|VIEW) IF NOT EXISTS ", statement), statement


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
    ],
)
def test_table_sort_keys(table, order_by):
    assert f"\n{order_by}\n" in table_statement(table)


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


def test_main_applies_the_schema_file(monkeypatch, capsys):
    client = FakeClient()
    monkeypatch.setattr(apply_log_schema, "admin_client", lambda: client)
    assert apply_log_schema.main([]) == 0
    assert client.commands == schema_statements()
    assert f"{len(client.commands)} statements" in capsys.readouterr().out
