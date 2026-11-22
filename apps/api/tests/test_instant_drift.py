"""Schema drift: the source's columns now against those an instant pack was built from (DECISIONS §11 step 0)."""

from app.onboarding.drift import read_snapshot, schema_drift, write_snapshot
from app.sources.inspect import CatalogColumn
from app.sources.store import StoredTable


def _table(name, columns):
    return StoredTable(
        source_id="shop", name=name, kind="table", selected=True, mode="copy", proposed_mode="copy", reason="",
        row_estimate=1, size_bytes=1, columns=tuple(CatalogColumn(c, kind, True, i) for i, (c, kind) in enumerate(columns, 1)),
        primary_key=(), foreign_keys=(), unusual_columns=(), interval_seconds=86400, cursor_column=None,
        cursor_value=None, next_run_at=None, last_synced_at=None, last_rows=None,
    )


BUILT = [_table("sales", [("sale_id", "integer"), ("sold_on", "text"), ("note", "text")]), _table("widgets", [("widget_id", "integer")])]


def test_the_snapshot_keeps_the_source_and_each_chosen_tables_columns(tmp_path):
    write_snapshot(tmp_path, "shop", BUILT)

    assert read_snapshot(tmp_path) == {"source": "shop", "tables": {
        "sales": [["sale_id", "integer"], ["sold_on", "text"], ["note", "text"]], "widgets": [["widget_id", "integer"]]}}
    assert read_snapshot(tmp_path / "missing") is None


def test_added_removed_and_retyped_columns_and_a_vanished_table_are_reported(tmp_path):
    write_snapshot(tmp_path, "shop", BUILT)
    now = [_table("sales", [("sale_id", "bigint"), ("sold_on", "text"), ("promo_code", "text")])]

    drift = schema_drift(read_snapshot(tmp_path), now)

    assert drift == [
        {"table": "sales", "added": ["promo_code"], "removed": ["note"],
         "retyped": [{"column": "sale_id", "before": "integer", "after": "bigint"}], "missing": False},
        {"table": "widgets", "added": [], "removed": ["widget_id"], "retyped": [], "missing": True},
    ]


def test_an_unchanged_source_has_no_drift(tmp_path):
    write_snapshot(tmp_path, "shop", BUILT)

    assert schema_drift(read_snapshot(tmp_path), BUILT) == []
