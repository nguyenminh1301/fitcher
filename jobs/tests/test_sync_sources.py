import re

import pytest

from jobs import sync_sources
from jobs.lib.source_manifest import ColumnSpec, SourceManifest, TableSpec
from jobs.load_data import LoadError


class FakeClient:
    """Records SQL; models raw tables and the rows each source table holds."""

    def __init__(self, source_rows, existing=(), fail_on=None):
        self.source_rows = source_rows
        self.tables = {name: 0 for name in existing}
        self.sql = []
        self.fail_on = fail_on

    def command(self, sql):
        self.sql.append(sql)
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError("source unreachable")
        if m := re.fullmatch(r"EXISTS TABLE `(\w+)`\.`(\w+)`", sql):
            return int(f"{m[1]}.{m[2]}" in self.tables)
        if m := re.fullmatch(r"SELECT count\(\) FROM `(\w+)`\.`(\w+)`", sql):
            name = f"{m[1]}.{m[2]}"
            return self.tables[name] if name in self.tables else self.source_rows[m[2]]
        if m := re.match(r"CREATE TABLE `(\w+)`\.`(\w+)` ENGINE = MergeTree ORDER BY tuple\(\) AS SELECT \* FROM \w+\(\w+, \w+ = '([\w./]+)'", sql):
            self.tables[f"{m[1]}.{m[2]}"] = self.source_rows[m[3]]
        elif m := re.fullmatch(r"DROP TABLE (?:IF EXISTS )?`(\w+)`\.`(\w+)`", sql):
            self.tables.pop(f"{m[1]}.{m[2]}", None)
        elif m := re.fullmatch(r"RENAME TABLE `(\w+)`\.`(\w+)` TO `(\w+)`\.`(\w+)`", sql):
            self.tables[f"{m[3]}.{m[4]}"] = self.tables.pop(f"{m[1]}.{m[2]}")
        elif m := re.fullmatch(r"EXCHANGE TABLES `(\w+)`\.`(\w+)` AND `(\w+)`\.`(\w+)`", sql):
            a, b = f"{m[1]}.{m[2]}", f"{m[3]}.{m[4]}"
            self.tables[a], self.tables[b] = self.tables[b], self.tables[a]
        return None


def manifest(*tables, kind="postgres", mode="copy"):
    return SourceManifest(name="shop", dbt_tag="shop", tables=tables, kind=kind, mode=mode, connection_env="SHOP")


TABLES = (TableSpec("orders", expected_rows=3), TableSpec("items", source="order_items"))


def test_copy_loads_every_table_then_publishes_it():
    client = FakeClient({"orders": 3, "order_items": 7})
    results = sync_sources.sync_source(manifest(*TABLES), client)

    assert [(r.name, r.expected_rows, r.loaded_rows, r.ok) for r in results] == [
        ("orders", 3, 3, True),
        ("items", None, 7, True),
    ]
    assert (
        "CREATE TABLE `raw`.`shop__orders__loading` ENGINE = MergeTree ORDER BY tuple() "
        "AS SELECT * FROM postgresql(shop, table = 'orders')"
    ) in client.sql
    assert client.tables == {"raw.shop__orders": 3, "raw.shop__items": 7}
    assert "RENAME TABLE `raw`.`shop__orders__loading` TO `raw`.`shop__orders`" in client.sql


def test_copy_replaces_a_previous_copy_by_exchange():
    client = FakeClient({"orders": 3, "order_items": 7}, existing=["raw.shop__orders", "raw.shop__items"])
    sync_sources.sync_source(manifest(*TABLES), client)

    exchange = client.sql.index("EXCHANGE TABLES `raw`.`shop__orders__loading` AND `raw`.`shop__orders`")
    assert client.sql[exchange + 1] == "DROP TABLE `raw`.`shop__orders__loading`"
    assert client.tables == {"raw.shop__orders": 3, "raw.shop__items": 7}


def test_copy_with_a_row_count_mismatch_publishes_nothing():
    client = FakeClient({"orders": 2, "order_items": 7}, existing=["raw.shop__orders"])
    with pytest.raises(LoadError, match="orders") as raised:
        sync_sources.sync_source(manifest(*TABLES), client)

    assert [(r.name, r.ok) for r in raised.value.results] == [("orders", False), ("items", True)]
    assert not any(s.startswith(("RENAME", "EXCHANGE")) for s in client.sql)
    assert client.tables == {"raw.shop__orders": 0}


def test_copy_failure_drops_the_loading_tables():
    client = FakeClient({"orders": 3, "order_items": 7}, fail_on="order_items")
    with pytest.raises(LoadError, match="items"):
        sync_sources.sync_source(manifest(*TABLES), client)
    assert client.tables == {}


def test_copy_drops_stale_loading_tables_first():
    client = FakeClient({"orders": 3, "order_items": 7}, existing=["raw.shop__orders__loading"])
    sync_sources.sync_source(manifest(*TABLES), client)
    assert client.sql[0] == "DROP TABLE IF EXISTS `raw`.`shop__orders__loading`"


def test_live_defines_the_engines_and_counts_each_table():
    columns = (ColumnSpec("order_id", "String"),)
    source = manifest(TableSpec("orders", expected_rows=3, columns=columns), kind="mongodb", mode="live")
    client = FakeClient({"orders": 3})

    results = sync_sources.sync_source(source, client)

    assert client.sql == [
        "CREATE DATABASE IF NOT EXISTS `src_shop`",
        "CREATE OR REPLACE TABLE `src_shop`.`orders` (`order_id` String) ENGINE = MongoDB(shop, collection = 'orders')",
        "SELECT count() FROM `src_shop`.`orders`",
    ]
    assert [(r.name, r.loaded_rows, r.ok) for r in results] == [("orders", 3, True)]


def test_live_reports_a_row_count_mismatch():
    client = FakeClient({"orders": 1, "order_items": 7})
    with pytest.raises(LoadError, match="orders"):
        sync_sources.sync_source(manifest(*TABLES, mode="live"), client)


def test_mode_override_switches_a_copy_source_to_live():
    source = sync_sources.with_mode(manifest(*TABLES), "live")
    assert source.mode == "live"
    assert sync_sources.with_mode(source, None) is source


def test_huggingface_sources_are_refused():
    source = manifest(TableSpec("orders", file="a.parquet", format="parquet", expected_rows=1), kind="huggingface")
    with pytest.raises(ValueError, match="load_data"):
        sync_sources.sync_source(source, FakeClient({}))


def test_cli_prints_the_summary(monkeypatch, capsys, tmp_path):
    client = FakeClient({"orders": 3, "order_items": 7})
    monkeypatch.setattr(sync_sources, "load_manifest", lambda name: manifest(*TABLES))
    monkeypatch.setattr(sync_sources, "sources_client", lambda: client)

    assert sync_sources.main(["--source", "shop"]) == 0
    out = capsys.readouterr().out
    assert "orders" in out and "Copied 2 tables of shop into raw" in out


def test_cli_reports_a_failed_sync(monkeypatch, capsys):
    client = FakeClient({"orders": 2, "order_items": 7})
    monkeypatch.setattr(sync_sources, "load_manifest", lambda name: manifest(*TABLES))
    monkeypatch.setattr(sync_sources, "sources_client", lambda: client)

    assert sync_sources.main(["--source", "shop"]) == 1
    assert "nothing was published" in capsys.readouterr().err
