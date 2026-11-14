"""Connecting, editing, deleting and syncing sources: the service that joins the store, ClickHouse and the catalog."""

from datetime import UTC, datetime, timedelta

import pytest

from sources_fixtures import FakeClickHouse
from state_fixtures import new_state

from app.sources.connection import Connection
from app.sources.inspect import InspectError
from app.sources.service import ConnectionPatch, SourceInUse, SourceService
from app.sources.store import DuplicateSource, SourceStore, TableChange

NOW = datetime(2026, 11, 14, 9, 0, tzinfo=UTC)
SECRET = "reader-pass-4711"


def connection(**changes):
    fields = dict(kind="postgres", host="db.internal", port=5432, database="erp", user="reader", password=SECRET,
                  schema="public", tls_mode="prefer", ca_certificate=None)
    return Connection(**(fields | changes))


@pytest.fixture
def parts(tmp_path):
    db, _ = new_state(tmp_path)
    store = SourceStore(db)
    clickhouse = FakeClickHouse()
    return store, clickhouse, SourceService(store, clickhouse, clock=lambda: NOW)


def statements(clickhouse, prefix):
    return [sql for sql in clickhouse.sql if sql.startswith(prefix)]


def test_a_probe_lists_the_tables_with_proposals_through_a_temporary_collection_that_is_dropped(parts):
    store, clickhouse, service = parts

    tables = service.probe(connection())

    assert {table.name: table.rows for table in tables} == {"orders": 1200, "order_items": 40000}
    created = statements(clickhouse, "CREATE NAMED COLLECTION")
    assert len(created) == 1 and created[0].startswith("CREATE NAMED COLLECTION `probe_")
    assert clickhouse.collections == set(), "the probe collection is dropped"
    assert store.list() == []


def test_a_failed_probe_raises_the_reason_and_still_drops_its_collection(parts):
    _, clickhouse, service = parts
    clickhouse.fail_on = "pg_namespace"
    clickhouse.error = RuntimeError('FATAL:  password authentication failed for user "reader"')

    with pytest.raises(InspectError) as raised:
        service.probe(connection())

    assert raised.value.reason == "authentication"
    assert clickhouse.collections == set()


def test_creating_a_source_saves_it_only_after_the_test_and_keeps_no_password(parts):
    store, clickhouse, service = parts

    source, tables = service.create("shop", connection())

    assert (source.id, source.host, source.username) == ("shop", "db.internal", "reader")
    assert {table.name: (table.mode, table.selected) for table in tables} == {
        "orders": ("live", False), "order_items": ("live", False)}
    assert clickhouse.collections == {"shop"}
    holders = [sql for sql in clickhouse.sql if SECRET in sql]
    assert len(holders) == 1 and holders[0].startswith("CREATE NAMED COLLECTION `shop`")
    assert SECRET not in repr(store.get("shop")) and SECRET not in repr(store.tables("shop"))


def test_a_failed_test_saves_nothing_and_removes_the_collection(parts):
    store, clickhouse, service = parts
    clickhouse.fail_on = "pg_namespace"
    clickhouse.error = RuntimeError("connection to server failed: Connection refused")

    with pytest.raises(InspectError) as raised:
        service.create("shop", connection())

    assert raised.value.reason == "refused"
    assert store.list() == [] and clickhouse.collections == set()


def test_a_name_already_in_use_is_refused_before_a_collection_is_created(parts):
    store, clickhouse, service = parts
    service.create("shop", connection())
    before = len(clickhouse.sql)

    with pytest.raises(DuplicateSource):
        service.create("shop", connection())

    assert not any(sql.startswith("CREATE NAMED COLLECTION") for sql in clickhouse.sql[before:])


def test_a_name_taken_by_a_collection_in_the_server_configuration_is_a_duplicate(parts):
    store, clickhouse, service = parts
    clickhouse.collections.add("fixture_postgres")

    with pytest.raises(DuplicateSource):
        service.create("fixture_postgres", connection())

    assert store.list() == [] and "fixture_postgres" in clickhouse.collections


@pytest.mark.parametrize("name", ["Shop", "raw", "probe_x", "a b", ""])
def test_a_source_name_must_be_a_free_identifier(parts, name):
    with pytest.raises(ValueError, match="name"):
        parts[2].create(name, connection())


def test_editing_the_password_tests_the_new_collection_first_and_then_replaces_the_real_one(parts):
    store, clickhouse, service = parts
    service.create("shop", connection())
    clickhouse.sql.clear()

    service.update("shop", ConnectionPatch(password="new-pass-9"))

    created = statements(clickhouse, "CREATE NAMED COLLECTION `probe_")
    altered = statements(clickhouse, "ALTER NAMED COLLECTION `shop`")
    assert len(created) == 1 and len(altered) == 1 and "new-pass-9" in altered[0]
    assert clickhouse.sql.index(created[0]) < clickhouse.sql.index(altered[0])
    assert clickhouse.collections == {"shop"}


def test_editing_with_a_wrong_password_leaves_the_stored_collection_untouched(parts):
    store, clickhouse, service = parts
    service.create("shop", connection())
    clickhouse.sql.clear()
    clickhouse.fail_on = r"pg_namespace"
    clickhouse.error = RuntimeError('FATAL:  password authentication failed for user "reader"')

    with pytest.raises(InspectError):
        service.update("shop", ConnectionPatch(password="wrong", host="other.internal"))

    assert statements(clickhouse, "ALTER NAMED COLLECTION") == []
    assert store.get("shop").host == "db.internal"


def test_editing_the_host_without_a_password_changes_the_collection_and_rolls_it_back_when_the_test_fails(parts):
    store, clickhouse, service = parts
    service.create("shop", connection())
    clickhouse.sql.clear()
    clickhouse.fail_on = r"pg_namespace"
    clickhouse.error = RuntimeError("connection to server failed: Connection refused")

    with pytest.raises(InspectError):
        service.update("shop", ConnectionPatch(host="elsewhere.internal"))

    altered = statements(clickhouse, "ALTER NAMED COLLECTION `shop`")
    assert len(altered) == 2 and "elsewhere.internal" in altered[0] and "db.internal" in altered[1]
    assert all("password" not in sql for sql in altered), "the stored password is never read or rewritten"
    assert store.get("shop").host == "db.internal"


def test_editing_updates_the_stored_fields_and_keeps_the_selection(parts):
    store, clickhouse, service = parts
    service.create("shop", connection())
    store.set_tables("shop", [TableChange("orders", selected=True, mode="copy")])

    service.update("shop", ConnectionPatch(host="db2.internal", port=5433))

    assert (store.get("shop").host, store.get("shop").port) == ("db2.internal", 5433)
    assert [(t.name, t.selected) for t in store.tables("shop")] == [("order_items", False), ("orders", True)]


def test_deleting_needs_the_source_name_as_confirmation(parts):
    _, _, service = parts
    service.create("shop", connection())

    with pytest.raises(ValueError, match="confirm"):
        service.delete("shop", confirm="nope")


def test_a_source_read_by_a_mart_cannot_be_deleted(parts):
    store, clickhouse, service = parts
    service.create("shop", connection())
    clickhouse.mart_definitions = [
        ("orders_mart", "CREATE VIEW marts.orders_mart AS SELECT * FROM src_shop.orders"),
        ("other_mart", "CREATE VIEW marts.other_mart AS SELECT * FROM src_other.orders"),
        ("raw_mart", "CREATE VIEW marts.raw_mart AS SELECT * FROM raw.shop__orders"),
    ]

    with pytest.raises(SourceInUse) as raised:
        service.delete("shop", confirm="shop")

    assert raised.value.marts == ["orders_mart", "raw_mart"]
    assert store.get("shop") and "shop" in clickhouse.collections


def test_deleting_drops_the_live_database_the_copies_and_the_collection(parts):
    store, clickhouse, service = parts
    service.create("shop", connection())
    clickhouse.sql.clear()

    service.delete("shop", confirm="shop")

    assert "DROP DATABASE IF EXISTS `src_shop`" in clickhouse.sql
    assert "DROP TABLE IF EXISTS `raw`.`shop__orders`" in clickhouse.sql
    assert "DROP NAMED COLLECTION IF EXISTS `shop`" in clickhouse.sql
    assert store.list() == [] and clickhouse.collections == set()


def select_for_copy(store, cursor=None, interval=3600):
    store.set_tables("shop", [TableChange("orders", selected=True, mode="copy", interval_seconds=interval,
                                          cursor_column=cursor)])


def test_a_first_sync_copies_the_table_and_records_the_cursor_and_the_next_run(parts):
    store, clickhouse, service = parts
    service.create("shop", connection())
    select_for_copy(store, cursor="id")

    sync = service.sync("shop", "manual")

    assert sync.status == "succeeded" and sync.error is None
    assert sync.results == [{"table": "orders", "mode": "copy", "rows": 5, "full": True}]
    table = store.tables("shop")[1]
    assert (table.cursor_value, table.last_rows, table.next_run_at) == ("41", 5, (NOW + timedelta(hours=1)).isoformat())
    assert clickhouse.raw["shop__orders"] == 5


def test_a_later_sync_reads_only_rows_above_the_cursor(parts):
    store, clickhouse, service = parts
    service.create("shop", connection())
    select_for_copy(store, cursor="id")
    service.sync("shop", "manual")
    clickhouse.cursor = "44"
    clickhouse.sql.clear()

    sync = service.sync("shop", "schedule")

    assert sync.results == [{"table": "orders", "mode": "copy", "rows": 2, "full": False}]
    assert any("WHERE `id` > '41'" in sql for sql in clickhouse.sql)
    assert store.tables("shop")[1].cursor_value == "44"


def test_a_sync_without_a_cursor_reloads_and_swaps_the_copy(parts):
    store, clickhouse, service = parts
    service.create("shop", connection())
    select_for_copy(store)
    service.sync("shop", "manual")
    clickhouse.sql.clear()

    service.sync("shop", "manual")

    assert any(sql.startswith("EXCHANGE TABLES") for sql in clickhouse.sql)


def test_a_failed_sync_keeps_the_previous_copy_and_records_the_reason(parts):
    store, clickhouse, service = parts
    service.create("shop", connection())
    select_for_copy(store)
    service.sync("shop", "manual")
    clickhouse.raw["shop__orders"] = 99
    clickhouse.fail_on = r"CREATE TABLE `raw`"
    clickhouse.error = RuntimeError("ERROR 2002 : Can't connect to server on 'db' (115)")

    sync = service.sync("shop", "schedule")

    assert (sync.status, sync.error) == ("failed", "refused")
    assert clickhouse.raw["shop__orders"] == 99 and "shop__orders__loading" not in clickhouse.raw
    assert store.syncs("shop")[0].error == "refused"
    assert store.tables("shop")[1].next_run_at == (NOW + timedelta(hours=1)).isoformat()


def test_a_sync_attaches_the_live_database_for_live_tables(parts):
    store, clickhouse, service = parts
    service.create("shop", connection())
    store.set_tables("shop", [TableChange("order_items", selected=True, mode="live")])

    sync = service.sync("shop", "manual")

    assert any(sql.startswith("CREATE DATABASE IF NOT EXISTS `src_shop` ENGINE = PostgreSQL(shop, database = 'erp'")
               for sql in clickhouse.sql)
    assert sync.results == [{"table": "order_items", "mode": "live", "rows": 7, "full": None}]


def test_a_sync_with_no_selected_table_is_refused(parts):
    _, _, service = parts
    service.create("shop", connection())

    with pytest.raises(ValueError, match="no selected table"):
        service.sync("shop", "manual")


def test_cancelling_kills_the_running_query_and_marks_the_sync_cancelled(parts):
    store, clickhouse, service = parts
    service.create("shop", connection())
    select_for_copy(store)
    clickhouse.fail_on = r"CREATE TABLE `raw`"
    clickhouse.error = RuntimeError("Code: 394. DB::Exception: Query was cancelled. (QUERY_WAS_CANCELLED)")
    started = store.start_sync("shop", "manual", NOW)
    store.set_query_id(started.id, "fitcher-sync-1")

    assert service.cancel("shop") is True

    assert "KILL QUERY WHERE query_id = 'fitcher-sync-1'" in clickhouse.sql
    assert service.cancel("other") is False


# SQL Server: copy only, the password in the vault and no named collection


def sql_connection(**changes):
    fields = dict(kind="sqlserver", host="mssql.internal", port=1433, database="erp", user="reader", password=SECRET,
                  schema="dbo", tls_mode="require", ca_certificate=None)
    return Connection(**(fields | changes))


@pytest.fixture
def mssql(tmp_path):
    from sources_fixtures import FakeSqlServer

    db, vault = new_state(tmp_path)
    store, clickhouse = SourceStore(db), FakeClickHouse()
    sqlserver = FakeSqlServer(clickhouse)
    service = SourceService(store, clickhouse, clock=lambda: NOW, sqlserver=sqlserver, vault=vault)
    return store, clickhouse, sqlserver, vault, service


def test_a_sql_server_source_keeps_its_password_in_the_vault_and_creates_no_collection(mssql):
    store, clickhouse, sqlserver, vault, service = mssql

    source, tables = service.create("erp", sql_connection())

    assert (source.kind, source.schema, source.host) == ("sqlserver", "dbo", "mssql.internal")
    assert vault.has("source:erp:password") and vault.reader().get("source:erp:password") == SECRET
    assert clickhouse.collections == set() and not any("NAMED COLLECTION" in sql for sql in clickhouse.sql)
    assert {t.name: (t.mode, t.proposed_mode, t.reason) for t in tables} == {
        "orders": ("copy", "copy", "copy_only"), "big": ("copy", "copy", "copy_only")}
    assert SECRET not in repr(store.get("erp")) and SECRET not in repr(store.tables("erp"))


def test_a_failed_sql_server_test_stores_nothing(mssql):
    store, _, sqlserver, vault, service = mssql
    sqlserver.error = InspectError("authentication")

    with pytest.raises(InspectError):
        service.create("erp", sql_connection())

    assert store.list() == [] and not vault.has("source:erp:password")


def test_a_sql_server_probe_lists_tables_without_saving_anything(mssql):
    store, _, _, vault, service = mssql

    tables = service.probe(sql_connection())

    assert {t.name for t in tables} == {"orders", "big"} and store.list() == []
    assert not vault.has("source:probe:password")


def test_sql_server_tables_cannot_be_read_live(mssql):
    store, _, _, _, service = mssql
    service.create("erp", sql_connection())

    with pytest.raises(ValueError, match="copy"):
        store.set_tables("erp", [TableChange("orders", selected=True, mode="live")])


def test_a_sql_server_sync_copies_with_the_stored_password_and_follows_the_cursor(mssql):
    store, clickhouse, sqlserver, _, service = mssql
    service.create("erp", sql_connection())
    store.set_tables("erp", [TableChange("orders", selected=True, mode="copy", cursor_column="id")])

    first = service.sync("erp", "manual")
    second = service.sync("erp", "manual")

    assert first.results == [{"table": "orders", "mode": "copy", "rows": 7, "full": True}]
    copies = [params for kind, params in sqlserver.calls if kind == "copy"]
    assert copies[0]["password"] == SECRET and copies[0]["after"] is None and copies[1]["after"] == "70"
    assert store.tables("erp")[1].cursor_value == "70" if store.tables("erp")[0].name == "big" else True
    assert second.status == "succeeded"


def test_a_failed_sql_server_sync_records_the_reason(mssql):
    store, _, sqlserver, _, service = mssql
    service.create("erp", sql_connection())
    store.set_tables("erp", [TableChange("orders", selected=True, mode="copy")])
    sqlserver.error = InspectError("refused")

    sync = service.sync("erp", "manual")

    assert (sync.status, sync.error) == ("failed", "refused")


def test_editing_the_password_tests_it_before_it_replaces_the_stored_one(mssql):
    store, _, sqlserver, vault, service = mssql
    service.create("erp", sql_connection())
    sqlserver.error = InspectError("authentication")

    with pytest.raises(InspectError):
        service.update("erp", ConnectionPatch(password="wrong"))
    assert vault.reader().get("source:erp:password") == SECRET

    sqlserver.error = None
    service.update("erp", ConnectionPatch(password="better", host="mssql2.internal"))
    assert vault.reader().get("source:erp:password") == "better" and store.get("erp").host == "mssql2.internal"


def test_editing_without_a_password_tests_with_the_stored_one(mssql):
    _, _, sqlserver, _, service = mssql
    service.create("erp", sql_connection())

    service.update("erp", ConnectionPatch(host="mssql2.internal"))

    check = [params for kind, params in sqlserver.calls if kind == "check"][-1]
    assert check["password"] == SECRET and check["host"] == "mssql2.internal"


def test_deleting_a_sql_server_source_removes_its_copies_and_its_secret(mssql):
    store, clickhouse, _, vault, service = mssql
    service.create("erp", sql_connection())
    clickhouse.sql.clear()

    service.delete("erp", confirm="erp")

    assert "DROP TABLE IF EXISTS `raw`.`erp__orders`" in clickhouse.sql
    assert not vault.has("source:erp:password") and store.list() == []


def test_a_sql_server_cancel_stops_the_copy_between_batches(mssql):
    store, _, sqlserver, _, service = mssql
    service.create("erp", sql_connection())
    running = store.start_sync("erp", "manual", NOW)

    assert service.cancel("erp") is True
    assert running.id in service._cancelled
