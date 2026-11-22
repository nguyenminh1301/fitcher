"""The source endpoints over a temporary app state and a fake ClickHouse; only an admin reaches them (DECISIONS §9, §15)."""

import logging
import time

from fastapi.testclient import TestClient
import pytest

from io import BytesIO

from sources_fixtures import FakeSqlServer, UploadClickHouse
from state_fixtures import new_state

from app.api import runtime, setup as setup_api, sources as sources_api
from app.main import app
from app.sources.files import FileService
from app.sources.service import SourceService
from app.sources.store import SourceStore

ADMIN = {}
VIEWER = {}
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
    db, vault = new_state(tmp_path)
    store, clickhouse, actions = SourceStore(db), UploadClickHouse(), Actions()
    files = FileService(store, clickhouse, tmp_path / "uploads", max_bytes=2048)
    sqlserver = FakeSqlServer(clickhouse)
    service = SourceService(store, clickhouse, files=files, sqlserver=sqlserver, vault=vault)
    app.dependency_overrides[sources_api.get_file_service] = lambda: files
    app.dependency_overrides[setup_api.get_state_db] = lambda: db
    app.dependency_overrides[sources_api.get_source_store] = lambda: store
    app.dependency_overrides[sources_api.get_source_service] = lambda: service
    app.dependency_overrides[runtime.get_admin_action_log] = lambda: actions
    app.dependency_overrides[sources_api.get_pack_status] = lambda: lambda name: ("none", 0, None)
    yield TestClient(app), store, clickhouse, actions, vault, sqlserver
    app.dependency_overrides.clear()


@pytest.fixture
def client(parts):
    return parts[0]


def connect(client, name="shop", **changes):
    response = client.post("/sources", headers=ADMIN, json={"name": name, **BODY, **changes})
    assert response.status_code == 201, response.text
    return response.json()


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


def test_connecting_a_source_answers_the_setups_data_step_and_a_failed_connection_does_not(client, parts):
    def data_step():
        steps = client.get("/setup/status", headers=ADMIN).json()["steps"]
        return next(step["state"] for step in steps if step["id"] == "data")

    parts[2].fail_on = "pg_namespace"
    client.post("/sources", headers=ADMIN, json={"name": "shop", **BODY})
    assert data_step() == "pending"
    parts[2].fail_on = None

    connect(client)

    assert data_step() == "done"


MSSQL = {"kind": "sqlserver", "host": "mssql.internal", "database": "erp", "user": "reader", "password": PASSWORD}


def test_a_sql_server_source_defaults_to_port_1433_schema_dbo_and_required_encryption(client, parts):
    created = client.post("/sources", headers=ADMIN, json={"name": "erp", **MSSQL})

    assert created.status_code == 201, created.text
    body = created.json()
    assert (body["kind"], body["port"], body["schema_name"], body["tls_mode"]) == ("sqlserver", 1433, "dbo", "require")
    assert {t["name"]: (t["mode"], t["proposed_mode"], t["reason"]) for t in body["tables"]} == {
        "orders": ("copy", "copy", "copy_only"), "big": ("copy", "copy", "copy_only")}
    login = [params for kind, params in parts[5].calls if kind == "check"][0]
    assert login["port"] == 1433 and login["tls_mode"] == "require"
    assert parts[4].has("source:erp:password") and PASSWORD not in created.text
    assert not any("NAMED COLLECTION" in sql for sql in parts[2].sql)


def test_testing_a_sql_server_connection_proposes_a_copy_for_every_table(client):
    response = client.post("/sources/test", headers=ADMIN, json=MSSQL)

    assert response.status_code == 200
    assert {t["proposed_mode"] for t in response.json()["tables"]} == {"copy"}


def test_a_sql_server_table_cannot_be_chosen_live_and_its_certificate_cannot_be_verified(client):
    client.post("/sources", headers=ADMIN, json={"name": "erp", **MSSQL})

    live = client.put("/sources/erp/tables", headers=ADMIN, json={"tables": [{"name": "orders", "mode": "live"}]})
    verify = client.post("/sources/test", headers=ADMIN, json={**MSSQL, "tls_mode": "verify"})

    assert live.status_code == 422 and "copy" in live.json()["detail"]
    assert verify.status_code == 422 and "certificate" in verify.json()["detail"]


def test_a_failed_sql_server_test_answers_with_one_fixed_reason(client, parts):
    from app.sources.inspect import InspectError

    parts[5].error = InspectError("tls")

    response = client.post("/sources/test", headers=ADMIN, json=MSSQL)

    assert response.status_code == 422 and response.json() == {"detail": {"reason": "tls"}}


def test_drift_compares_the_catalog_with_the_columns_the_instant_pack_was_built_from(client, parts, tmp_path, monkeypatch):
    from app.onboarding.drift import write_snapshot
    from app.sources.inspect import CatalogColumn

    store = parts[1]
    connect(client)
    monkeypatch.setenv("PACKS_DIR", str(tmp_path / "packs"))
    assert client.get("/sources/shop/drift", headers=ADMIN).json() == {"pack": None, "changes": []}
    built = next(table for table in store.tables("shop") if table.name == "orders")
    (tmp_path / "packs" / "shop").mkdir(parents=True)
    write_snapshot(tmp_path / "packs" / "shop", "shop", [type(built)(**{**built.__dict__, "columns": (
        CatalogColumn("id", "integer", False, 1), CatalogColumn("gone", "text", True, 2))})])

    body = client.get("/sources/shop/drift?refresh=true", headers=ADMIN).json()

    assert body["pack"] == "shop"
    assert body["changes"] == [{"table": built.name, "added": ["created_at"], "removed": ["gone"], "retyped": [], "missing": False}]


def test_the_source_password_reaches_no_response_log_line_or_admin_action(client, parts, caplog):
    caplog.set_level(logging.DEBUG)
    bodies = [client.post("/sources", headers=ADMIN, json={"name": "shop", **BODY}).text,
              client.get("/sources", headers=ADMIN).text, client.get("/sources/shop", headers=ADMIN).text]
    parts[2].fail_on = "pg_namespace"
    parts[2].error = RuntimeError(f'FATAL:  password authentication failed for user "reader" {PASSWORD}')
    bodies.append(client.post("/sources/test", headers=ADMIN, json=BODY).text)
    assert all(PASSWORD not in text for text in [*bodies, caplog.text, repr(parts[3].records)])


def test_an_upload_named_with_a_path_stays_inside_the_upload_directory(client, parts, tmp_path):
    parts[2].inferred = [("id", "Nullable(String)")]

    uploaded = upload(client, "../../outside.csv")

    assert uploaded.status_code in (201, 422)
    assert not (tmp_path.parent / "outside.csv").exists() and not (tmp_path / "outside.csv").exists()
    assert all(path.resolve().is_relative_to((tmp_path / "uploads").resolve())
               for path in tmp_path.rglob("*outside*"))


def test_each_source_lists_the_status_of_its_own_pack(client):
    connect(client)
    connect(client, name="music")
    statuses = {"shop": ("ready", 3, None), "music": ("failed", 0, "the model did not answer")}
    app.dependency_overrides[sources_api.get_pack_status] = lambda: statuses.get

    listed = {source["id"]: source["pack"] for source in client.get("/sources", headers=ADMIN).json()}

    assert listed == {
        "shop": {"name": "shop", "status": "ready", "datasets": 3, "error": None},
        "music": {"name": "music", "status": "failed", "datasets": 0, "error": "the model did not answer"},
    }
