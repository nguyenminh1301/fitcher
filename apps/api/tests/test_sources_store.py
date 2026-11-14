"""Sources, their tables and their syncs in the app state; no credential is ever stored here."""

from datetime import UTC, datetime, timedelta
import sqlite3

import pytest

from state_fixtures import new_state

from app.sources.inspect import CatalogColumn, ForeignKey, TableInfo
from app.sources.store import (
    DuplicateSource, NewSource, SourceNotFound, SourceStore, SyncBusy, TableChange, TableNotFound,
)

NOW = datetime(2026, 11, 14, 9, 0, tzinfo=UTC)


@pytest.fixture
def store(tmp_path):
    db, _ = new_state(tmp_path)
    return SourceStore(db)


def new(name="shop", **changes):
    fields = dict(id=name, kind="postgres", host="db.internal", port=5432, database="erp", schema="public",
                  username="reader", tls_mode="prefer", has_ca=False)
    return NewSource(**(fields | changes))


def catalog():
    return [
        TableInfo("orders", "table", 1200, 400_000, columns=(CatalogColumn("id", "integer", False, 1),
                  CatalogColumn("created_at", "timestamp", False, 2)), primary_key=("id",),
                  foreign_keys=(ForeignKey(("customer_id",), "customers", ("id",)),), unusual_columns=("meta",)),
        TableInfo("big", "table", 9_000_000, 2 * 1024**3),
    ]


def test_a_source_is_stored_with_its_connection_and_no_password(store):
    store.create(new())

    stored = store.get("shop")
    assert (stored.kind, stored.host, stored.port, stored.database, stored.schema, stored.username) == (
        "postgres", "db.internal", 5432, "erp", "public", "reader")
    assert "password" not in {field for field in vars(stored)}


def test_the_state_has_no_column_that_could_hold_a_password(store):
    columns = {row[1] for table in ("sources", "source_tables", "source_syncs", "source_files")
               for row in store._db.connection().execute(f"PRAGMA table_info({table})")}

    assert not any("password" in column or "secret" in column for column in columns)


def test_a_source_name_is_unique(store):
    store.create(new())

    with pytest.raises(DuplicateSource):
        store.create(new())


def test_listing_and_looking_up_a_missing_source(store):
    store.create(new("a"))
    store.create(new("b"))

    assert [source.id for source in store.list()] == ["a", "b"]
    with pytest.raises(SourceNotFound):
        store.get("missing")


def test_editing_a_source_changes_its_connection_fields_only(store):
    store.create(new())

    store.update("shop", host="db2.internal", port=5433, tls_mode="require", has_ca=True)

    stored = store.get("shop")
    assert (stored.host, stored.port, stored.tls_mode, stored.has_ca, stored.database) == (
        "db2.internal", 5433, "require", True, "erp")


def test_the_catalog_is_saved_with_the_proposed_mode_and_a_selection_of_nothing(store):
    store.create(new())

    store.save_catalog("shop", catalog())

    tables = {table.name: table for table in store.tables("shop")}
    assert tables["orders"].proposed_mode == "live" and tables["orders"].reason == "small"
    assert tables["big"].proposed_mode == "copy" and tables["big"].reason == "rows"
    assert not tables["orders"].selected and tables["orders"].mode == "live"
    assert tables["orders"].primary_key == ("id",)
    assert tables["orders"].foreign_keys == (ForeignKey(("customer_id",), "customers", ("id",)),)
    assert tables["orders"].unusual_columns == ("meta",)
    assert [column.name for column in tables["orders"].columns] == ["id", "created_at"]


def test_saving_the_catalog_again_keeps_the_selection_and_drops_tables_that_vanished(store):
    store.create(new())
    store.save_catalog("shop", catalog())
    store.set_tables("shop", [TableChange("orders", selected=True, mode="copy", interval_seconds=3600,
                                          cursor_column="created_at")])

    store.save_catalog("shop", [catalog()[0]])

    tables = store.tables("shop")
    assert [table.name for table in tables] == ["orders"]
    assert (tables[0].selected, tables[0].mode, tables[0].interval_seconds, tables[0].cursor_column) == (
        True, "copy", 3600, "created_at")


def test_a_selection_is_validated_against_the_tables_of_the_source(store):
    store.create(new())
    store.save_catalog("shop", catalog())

    with pytest.raises(TableNotFound):
        store.set_tables("shop", [TableChange("nope", selected=True)])
    with pytest.raises(ValueError, match="interval"):
        store.set_tables("shop", [TableChange("orders", interval_seconds=10)])
    with pytest.raises(ValueError, match="mode"):
        store.set_tables("shop", [TableChange("orders", mode="both")])
    with pytest.raises(ValueError, match="cursor"):
        store.set_tables("shop", [TableChange("orders", cursor_column="nope")])


def test_changing_the_cursor_column_forgets_the_last_value_seen(store):
    store.create(new())
    store.save_catalog("shop", catalog())
    store.set_tables("shop", [TableChange("orders", selected=True, mode="copy", cursor_column="id")])
    store.record_table_sync("shop", "orders", rows=5, cursor_value="41", next_run_at=NOW)

    store.set_tables("shop", [TableChange("orders", cursor_column="created_at")])

    assert store.tables("shop")[0].cursor_value is None


def test_deleting_a_source_removes_its_tables_and_syncs(store):
    store.create(new())
    store.save_catalog("shop", catalog())
    store.start_sync("shop", "manual", NOW)

    store.delete("shop")

    assert store.list() == []
    assert store._db.connection().execute("SELECT count() FROM source_tables").fetchone() == (0,)
    assert store._db.connection().execute("SELECT count() FROM source_syncs").fetchone() == (0,)


# Syncs


def test_only_one_sync_runs_per_source_at_a_time(store):
    store.create(new())
    first = store.start_sync("shop", "manual", NOW)

    with pytest.raises(SyncBusy):
        store.start_sync("shop", "schedule", NOW)

    store.finish_sync(first.id, "succeeded", results=[], error=None, finished_at=NOW)
    assert store.start_sync("shop", "manual", NOW).id != first.id


def test_a_failed_sync_records_its_reason_and_the_last_result_is_listed_first(store):
    store.create(new())
    first = store.start_sync("shop", "manual", NOW)
    store.finish_sync(first.id, "succeeded", results=[{"table": "orders", "rows": 3}], error=None, finished_at=NOW)
    second = store.start_sync("shop", "schedule", NOW + timedelta(hours=1))
    store.finish_sync(second.id, "failed", results=[], error="authentication", finished_at=NOW + timedelta(hours=1))

    syncs = store.syncs("shop")

    assert [(sync.id, sync.status, sync.error) for sync in syncs] == [
        (second.id, "failed", "authentication"), (first.id, "succeeded", None)]
    assert syncs[1].results == [{"table": "orders", "rows": 3}]


def test_a_sync_whose_heartbeat_stopped_is_marked_interrupted_but_a_live_one_is_not(store):
    store.create(new())
    stale = store.start_sync("shop", "schedule", NOW)
    store.touch_sync(stale.id, NOW + timedelta(minutes=90))

    assert store.recover_interrupted(NOW + timedelta(minutes=91)) == 0
    assert store.recover_interrupted(NOW + timedelta(hours=2)) == 1

    assert store.syncs("shop")[0].status == "failed" and store.syncs("shop")[0].error == "interrupted"
    assert store.start_sync("shop", "manual", NOW + timedelta(hours=2)).id != stale.id


def test_the_due_check_claims_each_due_source_once_across_processes(tmp_path):
    db, _ = new_state(tmp_path)
    one, other = SourceStore(db), SourceStore(db)
    one.create(new())
    one.save_catalog("shop", catalog())
    one.set_tables("shop", [TableChange("orders", selected=True, mode="copy", interval_seconds=3600),
                            TableChange("big", selected=True, mode="live")])

    first = one.claim_due(NOW)
    second = other.claim_due(NOW)

    assert [(claim.source_id, claim.tables) for claim in first] == [("shop", ["orders"])]
    assert second == [], "the second process finds the source already syncing"


def test_a_table_is_due_again_after_its_interval(store):
    store.create(new())
    store.save_catalog("shop", catalog())
    store.set_tables("shop", [TableChange("orders", selected=True, mode="copy", interval_seconds=3600)])
    claim = store.claim_due(NOW)[0]
    store.record_table_sync("shop", "orders", rows=3, cursor_value=None, next_run_at=NOW + timedelta(hours=1))
    store.finish_sync(claim.sync_id, "succeeded", results=[], error=None, finished_at=NOW)

    assert store.claim_due(NOW + timedelta(minutes=59)) == []
    assert [claim.source_id for claim in store.claim_due(NOW + timedelta(hours=1))] == ["shop"]


def test_a_table_that_is_not_selected_or_is_live_is_never_due(store):
    store.create(new())
    store.save_catalog("shop", catalog())
    store.set_tables("shop", [TableChange("big", selected=False, mode="copy"),
                              TableChange("orders", selected=True, mode="live")])

    assert store.claim_due(NOW) == []


def test_the_raw_database_rejects_a_second_running_sync_even_when_written_directly(store):
    store.create(new())
    store.start_sync("shop", "manual", NOW)

    with pytest.raises(sqlite3.IntegrityError):
        with store._db.write() as conn:
            conn.execute("INSERT INTO source_syncs (source_id, started_by, status, started_at, heartbeat_at) "
                         "VALUES ('shop', 'manual', 'running', 'x', 'x')")
