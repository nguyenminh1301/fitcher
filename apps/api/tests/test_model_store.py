"""The ClickHouse model store and the gateway catalog client, over fakes."""

from datetime import datetime, UTC

import httpx
import pytest

from app.llm.model_store import CatalogClient, CatalogError, ClickHouseModelStore, model_tiers_client
from app.llm.tiers import TierStoreError
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


def test_a_failed_read_is_a_tier_store_error():
    with pytest.raises(TierStoreError, match="ConnectionError"):
        ClickHouseModelStore(FakeClient(fail=True)).read()


def test_write_and_record_action_insert_one_row_each():
    client = FakeClient()
    store = ClickHouseModelStore(client)

    store.write("sql-gen", "openai-large", "lab.admin", NOW)
    store.record_action(AdminActionRecord(
        ts=NOW, actor="lab.admin", action="model_tier", target="sql-gen", old_value="openai-medium", new_value="openai-large",
    ))

    assert client.inserts[0] == (
        "data_meta.model_tiers", [["sql-gen", "openai-large", "lab.admin", NOW]], ["tier", "alias", "changed_by", "changed_at"],
    )
    table, rows, columns = client.inserts[1]
    assert (table, columns) == ("agent_logs.admin_actions", ["ts", "actor", "action", "target", "old_value", "new_value"])
    assert rows == [[NOW, "lab.admin", "model_tier", "sql-gen", "openai-medium", "openai-large"]]


def test_reports_are_read_for_one_pack_newest_first():
    client = FakeClient([("r1", NOW, {"sql-gen": "openai-medium"}, 1, None)])

    [summary] = ClickHouseModelStore(client).reports("shop")

    assert (summary.report_id, summary.tiers, summary.passed, summary.regressed) == ("r1", {"sql-gen": "openai-medium"}, True, None)
    sql, parameters = client.queries[0]
    assert "ORDER BY ts DESC" in sql and parameters["pack"] == "shop"


def test_the_client_needs_its_password():
    with pytest.raises(RuntimeError, match="CLICKHOUSE_MODEL_TIERS_PASSWORD must be set"):
        model_tiers_client({})


def catalog(handler) -> CatalogClient:
    return CatalogClient("http://litellm:4000/", "sk-test", http=httpx.Client(transport=httpx.MockTransport(handler)))


def test_the_catalog_lists_the_loaded_aliases():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), request.headers["Authorization"]))
        return httpx.Response(200, json={"data": [{"id": "openai-small"}, {"id": "anthropic-small"}]})

    assert catalog(handler).aliases() == ["anthropic-small", "openai-small"]
    assert seen == [("http://litellm:4000/v1/models", "Bearer sk-test")]


@pytest.mark.parametrize("response", [httpx.Response(500), httpx.Response(200, json={"data": [{"name": "x"}]})])
def test_a_failed_listing_is_a_catalog_error(response):
    with pytest.raises(CatalogError):
        catalog(lambda request: response).aliases()
