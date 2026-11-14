"""The source endpoints over a temporary app state and a fake ClickHouse; only an admin reaches them (DECISIONS §9, §15)."""

import time

from fastapi.testclient import TestClient
import pytest

from session_fixtures import SessionHeaders
from io import BytesIO

from sources_fixtures import UploadClickHouse
from state_fixtures import new_state

from app.api import runtime, setup as setup_api, sources as sources_api
from app.main import app
from app.sources.files import FileService
from app.sources.service import SourceService
from app.sources.store import SourceStore
from app.state.settings import Settings

ADMIN = SessionHeaders(["admin"], user_id="lab.admin")
VIEWER = SessionHeaders()
PASSWORD = "reader-pass-4711-xyz"
BODY = {"kind": "postgres", "host": "db.internal", "port": 5432, "database": "erp", "schema_name": "public",
        "user": "reader", "password": PASSWORD, "tls_mode": "prefer"}


class Actions:
    def __init__(self):
        self.records = []

    def record_action(self, record) -> None:
        self.records.append(record)


@pytest.fixture
def parts(tmp_path):
    db, _ = new_state(tmp_path)
    Settings(db).set("instance", "mode", "team")
    store, clickhouse, actions = SourceStore(db), UploadClickHouse(), Actions()
    files = FileService(store, clickhouse, tmp_path / "uploads", max_bytes=2048)
    service = SourceService(store, clickhouse, files=files)
    app.dependency_overrides[sources_api.get_file_service] = lambda: files
    app.dependency_overrides[setup_api.get_state_db] = lambda: db
    app.dependency_overrides[sources_api.get_source_store] = lambda: store
    app.dependency_overrides[sources_api.get_source_service] = lambda: service
    app.dependency_overrides[runtime.get_admin_action_log] = lambda: actions
    yield TestClient(app), store, clickhouse, actions
    app.dependency_overrides.clear()


@pytest.fixture
def client(parts):
    return parts[0]


def connect(client, name="shop", **changes):
    response = client.post("/sources", headers=ADMIN, json={"name": name, **BODY, **changes})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize(("method", "path"), [
    ("get", "/sources"), ("post", "/sources/test"), ("post", "/sources"), ("patch", "/sources/shop"),
    ("delete", "/sources/shop"), ("get", "/sources/shop/tables"), ("put", "/sources/shop/tables"),
    ("post", "/sources/shop/sync"), ("post", "/sources/shop/sync/cancel"), ("get", "/sources/shop/syncs"),
    ("post", "/sources/files"), ("post", "/sources/files/abc/load"),
])
def test_every_endpoint_needs_the_admin_role(client, method, path):
    assert getattr(client, method)(path, headers=VIEWER).status_code == 403


def test_testing_a_connection_lists_the_tables_with_sizes_and_the_proposed_mode(client, parts):
    response = client.post("/sources/test", headers=ADMIN, json=BODY)

    assert response.status_code == 200
    tables = {table["name"]: table for table in response.json()["tables"]}
    assert (tables["orders"]["rows"], tables["orders"]["proposed_mode"], tables["orders"]["reason"]) == (1200, "live", "small")
    assert tables["order_items"]["rows"] == 40000 and tables["order_items"]["selected"] is False
    assert tables["orders"]["cursor_candidates"] == ["id", "created_at"]
    assert parts[1].list() == []


def test_a_failed_test_answers_with_one_fixed_reason(client, parts):
    parts[2].fail_on = "pg_namespace"
    parts[2].error = RuntimeError(f'FATAL:  password authentication failed for user "reader" {PASSWORD}')

    response = client.post("/sources/test", headers=ADMIN, json=BODY)

    assert response.status_code == 422
    assert response.json() == {"detail": {"reason": "authentication"}}


def test_a_source_is_connected_listed_and_never_shows_its_password(client):
    created = connect(client)
    listed = client.get("/sources", headers=ADMIN)

    assert created["id"] == "shop" and created["host"] == "db.internal" and created["user"] == "reader"
    assert len(created["tables"]) == 2 and created["selected_count"] == 0
    assert [source["id"] for source in listed.json()] == ["shop"]
    assert PASSWORD not in listed.text and PASSWORD not in str(created)


def test_a_duplicate_name_is_a_conflict_and_an_invalid_one_is_refused(client):
    connect(client)

    assert client.post("/sources", headers=ADMIN, json={"name": "shop", **BODY}).status_code == 409
    refused = client.post("/sources", headers=ADMIN, json={"name": "Not Valid", **BODY})
    assert refused.status_code == 422 and "name" in refused.text


def test_invalid_connection_fields_are_refused_without_reaching_clickhouse(client, parts):
    response = client.post("/sources/test", headers=ADMIN, json={**BODY, "host": "http://db"})

    assert response.status_code == 422
    assert parts[2].sql == []


def test_the_default_port_follows_the_kind(client, parts):
    body = {k: v for k, v in BODY.items() if k != "port"}

    client.post("/sources/test", headers=ADMIN, json=body)

    assert any("port = 5432" in sql for sql in parts[2].sql if sql.startswith("CREATE NAMED COLLECTION"))


def test_admin_actions_record_the_change_without_the_password(client, parts):
    connect(client)
    client.patch("/sources/shop", headers=ADMIN, json={"host": "db2.internal", "password": PASSWORD + "2"})
    client.delete("/sources/shop?confirm=shop", headers=ADMIN)

    actions = [(r.action, r.target) for r in parts[3].records]
    assert actions == [("source_add", "shop"), ("source_edit", "shop"), ("source_delete", "shop")]
    assert all(PASSWORD not in r.old_value + r.new_value for r in parts[3].records)


def test_editing_a_source_changes_its_fields(client):
    connect(client)

    body = client.patch("/sources/shop", headers=ADMIN, json={"host": "db2.internal", "port": 5433}).json()

    assert (body["host"], body["port"]) == ("db2.internal", 5433)
    assert client.patch("/sources/nope", headers=ADMIN, json={"host": "x"}).status_code == 404


def test_deleting_needs_the_confirmation_and_is_refused_while_a_mart_reads_the_source(client, parts):
    connect(client)
    assert client.delete("/sources/shop", headers=ADMIN).status_code == 422
    assert client.delete("/sources/shop?confirm=other", headers=ADMIN).status_code == 422
    parts[2].mart_definitions = [("m", "CREATE VIEW marts.m AS SELECT * FROM src_shop.orders")]

    refused = client.delete("/sources/shop?confirm=shop", headers=ADMIN)

    assert refused.status_code == 409 and refused.json()["detail"]["marts"] == ["m"]
    parts[2].mart_definitions = []
    assert client.delete("/sources/shop?confirm=shop", headers=ADMIN).status_code == 204
    assert client.get("/sources", headers=ADMIN).json() == []


def test_the_selection_mode_interval_and_cursor_are_saved(client):
    connect(client)

    response = client.put("/sources/shop/tables", headers=ADMIN, json={"tables": [
        {"name": "orders", "selected": True, "mode": "copy", "interval_seconds": 3600, "cursor_column": "id"},
        {"name": "order_items", "selected": True, "mode": "live"},
    ]})

    assert response.status_code == 200
    tables = {t["name"]: t for t in response.json()}
    assert (tables["orders"]["selected"], tables["orders"]["mode"], tables["orders"]["interval_seconds"],
            tables["orders"]["cursor_column"]) == (True, "copy", 3600, "id")
    assert tables["order_items"]["mode"] == "live"


def test_live_tables_tied_by_a_foreign_key_are_flagged_as_slow(client):
    connect(client)

    tables = {t["name"]: t for t in client.put("/sources/shop/tables", headers=ADMIN, json={"tables": [
        {"name": "orders", "selected": True, "mode": "live"}, {"name": "order_items", "selected": True, "mode": "live"},
    ]}).json()}

    assert tables["orders"]["slow"] and tables["order_items"]["slow"]


@pytest.mark.parametrize(("change", "status"), [
    ({"name": "nope", "selected": True}, 404),
    ({"name": "orders", "cursor_column": "nope"}, 422),
    ({"name": "orders", "interval_seconds": 10}, 422),
    ({"name": "orders", "mode": "both"}, 422),
])
def test_a_selection_that_does_not_fit_is_refused(client, change, status):
    connect(client)

    assert client.put("/sources/shop/tables", headers=ADMIN, json={"tables": [change]}).status_code == status


def wait_for_sync(client, name="shop"):
    for _ in range(200):
        syncs = client.get(f"/sources/{name}/syncs", headers=ADMIN).json()
        if syncs and syncs[0]["status"] != "running":
            return syncs
        time.sleep(0.02)
    raise AssertionError("the sync did not finish")


def test_a_sync_runs_in_the_background_and_its_result_is_listed(client, parts):
    connect(client)
    client.put("/sources/shop/tables", headers=ADMIN, json={"tables": [
        {"name": "orders", "selected": True, "mode": "copy", "cursor_column": "id"}]})

    started = client.post("/sources/shop/sync", headers=ADMIN)

    assert started.status_code == 202 and started.json()["status"] == "running"
    syncs = wait_for_sync(client)
    assert syncs[0]["status"] == "succeeded" and syncs[0]["results"][0]["rows"] == 5
    last = client.get("/sources", headers=ADMIN).json()[0]["last_sync"]
    assert last["status"] == "succeeded"


def test_a_sync_of_a_source_without_a_selected_table_is_refused_and_a_running_one_is_a_conflict(client, parts):
    connect(client)
    assert client.post("/sources/shop/sync", headers=ADMIN).status_code == 422
    client.put("/sources/shop/tables", headers=ADMIN, json={"tables": [{"name": "orders", "selected": True}]})
    parts[1].start_sync("shop", "schedule", __import__("datetime").datetime.now(__import__("datetime").UTC))

    assert client.post("/sources/shop/sync", headers=ADMIN).status_code == 409


def test_cancelling_a_sync_that_is_not_running_is_a_not_found(client):
    connect(client)

    assert client.post("/sources/shop/sync/cancel", headers=ADMIN).status_code == 404


def test_a_failed_sync_shows_only_its_reason(client, parts):
    connect(client)
    client.put("/sources/shop/tables", headers=ADMIN, json={"tables": [{"name": "orders", "selected": True, "mode": "copy"}]})
    parts[2].fail_on = r"CREATE TABLE `raw`"
    parts[2].error = RuntimeError(f"ERROR 1045 : Access denied for user 'reader' (using password: YES) {PASSWORD}")

    client.post("/sources/shop/sync", headers=ADMIN)
    syncs = wait_for_sync(client)

    assert (syncs[0]["status"], syncs[0]["error"]) == ("failed", "authentication")
    assert PASSWORD not in str(syncs)


def test_listing_tables_can_refresh_the_catalog(client, parts):
    connect(client)
    parts[2].catalog = {**parts[2].catalog, "pg_class": [("orders", "r", 99.0, 5, "100")]}

    stale = client.get("/sources/shop/tables", headers=ADMIN).json()
    fresh = client.get("/sources/shop/tables?refresh=true", headers=ADMIN).json()

    assert len(stale) == 2 and [t["name"] for t in fresh] == ["orders"]


def test_no_response_or_log_line_ever_contains_the_password(client, caplog):
    responses = [
        client.post("/sources/test", headers=ADMIN, json=BODY),
        client.post("/sources", headers=ADMIN, json={"name": "shop", **BODY}),
        client.get("/sources", headers=ADMIN),
        client.get("/sources/shop/tables", headers=ADMIN),
        client.patch("/sources/shop", headers=ADMIN, json={"password": PASSWORD + "x"}),
        client.get("/sources/shop/syncs", headers=ADMIN),
    ]

    assert all(PASSWORD not in response.text for response in responses)
    assert PASSWORD not in caplog.text


CSV = "id,amount,day\nA1,10.5,2024-01-02\nA2,3,2024-01-03\n".encode()


def upload(client, name="orders.csv", data=CSV, headers=ADMIN):
    return client.post("/sources/files", headers=headers, files={"file": (name, BytesIO(data), "text/csv")})


def test_an_uploaded_file_shows_its_inferred_types_and_loads_as_a_source(client, parts):
    parts[2].inferred = [("id", "Nullable(String)"), ("amount", "Nullable(Float64)"), ("day", "Nullable(Date)")]

    uploaded = upload(client)

    assert uploaded.status_code == 201
    body = uploaded.json()
    assert (body["format"], body["file_name"]) == ("csv", "orders.csv")
    assert [(c["name"], c["type"]) for c in body["columns"]] == [
        ("id", "Nullable(String)"), ("amount", "Nullable(Float64)"), ("day", "Nullable(Date)")]
    assert body["sample"][0] == ["A1", "10.5", "2024-01-02"]
    columns = [{"name": "id", "type": "Nullable(String)"}, {"name": "amount", "type": "Nullable(Decimal(18, 2))"},
               {"name": "day", "type": "Nullable(Date)"}]

    loaded = client.post(f"/sources/files/{body['id']}/load", headers=ADMIN, json={"columns": columns})

    assert loaded.status_code == 201
    detail = loaded.json()
    assert (detail["id"], detail["kind"], detail["selected_count"]) == ("orders", "file", 1)
    assert detail["tables"][0]["last_rows"] == 2 and detail["last_sync"]["status"] == "succeeded"
    assert parts[2].raw["orders__orders"] == 2


def test_syncing_a_file_source_reloads_the_stored_original(client, parts):
    parts[2].inferred = [("id", "Nullable(String)"), ("amount", "Nullable(Float64)"), ("day", "Nullable(Date)")]
    body = upload(client).json()
    client.post(f"/sources/files/{body['id']}/load", headers=ADMIN, json={"columns": body["columns"]})
    parts[2].inserted.clear()

    assert client.post("/sources/orders/sync", headers=ADMIN).status_code == 202
    syncs = wait_for_sync(client, "orders")

    assert syncs[0]["status"] == "succeeded" and parts[2].inserted[0][3] == CSV


def test_a_file_above_the_size_cap_is_refused_with_413(client):
    assert upload(client, data=b"a\n" + b"1\n" * 2000).status_code == 413


def test_a_file_of_an_unsupported_type_is_refused(client):
    assert upload(client, "x.csv", b"%PDF-1.7 not a table").status_code == 415
    assert upload(client, "x.csv", b"").status_code == 422


def test_a_load_with_a_type_that_is_not_allowed_is_refused_and_creates_nothing(client, parts):
    parts[2].inferred = [("id", "Nullable(String)"), ("amount", "Nullable(Float64)"), ("day", "Nullable(Date)")]
    body = upload(client).json()
    bad = [{"name": "id", "type": "String) ENGINE = Memory --"}, *body["columns"][1:]]

    response = client.post(f"/sources/files/{body['id']}/load", headers=ADMIN, json={"columns": bad})

    assert response.status_code == 422 and client.get("/sources", headers=ADMIN).json() == []


def test_a_load_for_an_unknown_upload_is_not_found(client):
    response = client.post("/sources/files/missing/load", headers=ADMIN, json={"columns": [{"name": "a", "type": "String"}]})

    assert response.status_code == 404
