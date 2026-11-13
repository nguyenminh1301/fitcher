"""The ClickHouse side of the Models page, over a fake client."""

from datetime import datetime, UTC

import pytest

from app.llm.model_store import ClickHouseModelStore, model_tiers_client
from app.observability.events import AdminActionRecord

NOW = datetime(2026, 11, 4, 8, 0, tzinfo=UTC)


class Rows:
    def __init__(self, rows):
        self.result_rows = rows


class FakeClient:
    def __init__(self, rows=None, fail=False):
        self.rows = rows or []
        self.fail = fail
        self.queries: list[tuple[str, dict | None]] = []
        self.inserts: list[tuple[str, list, list]] = []

    def query(self, sql, parameters=None):
        if self.fail:
            raise ConnectionError("clickhouse is down")
        self.queries.append((sql, parameters))
        return Rows(self.rows)

    def insert(self, table, rows, column_names):
        self.inserts.append((table, rows, column_names))


def test_read_takes_the_latest_alias_of_each_tier():
    client = FakeClient([("sql-small", "anthropic-small")])

    assert ClickHouseModelStore(client).read() == {"sql-small": "anthropic-small"}
    assert "argMax(alias, changed_at)" in client.queries[0][0] and "data_meta.model_tiers" in client.queries[0][0]


def test_reports_are_the_latest_per_tier_and_alias_of_one_pack():
    client = FakeClient([("sql-gen", "openai-medium", "r1", NOW, 1, None)])

    [summary] = ClickHouseModelStore(client).reports("shop")

    assert (summary.report_id, summary.tiers, summary.passed, summary.regressed) == ("r1", {"sql-gen": "openai-medium"}, True, None)
    sql, parameters = client.queries[0]
    assert "GROUP BY tier, alias" in sql and "LIMIT" not in sql and parameters["pack"] == "shop"


def test_the_client_needs_its_password():
    with pytest.raises(RuntimeError, match="CLICKHOUSE_MODEL_TIERS_PASSWORD must be set"):
        model_tiers_client({})


def test_record_action_inserts_one_row():
    client = FakeClient()

    ClickHouseModelStore(client).record_action(AdminActionRecord(
        ts=NOW, actor="lab.admin", action="model_tier", target="fast", old_value="openai/gpt-5.4-mini",
        new_value="openai/gpt-5.5",
    ))

    [(table, rows, columns)] = client.inserts
    assert table == "agent_logs.admin_actions" and rows[0][1] == "lab.admin" and columns[0] == "ts"
