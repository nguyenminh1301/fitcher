import pytest

from jobs.lib import source_engines
from jobs.lib.source_manifest import ColumnSpec, SourceManifest, TableSpec, load_manifest

COLUMNS = (ColumnSpec("order_id", "String"), ColumnSpec("quantity", "Nullable(Int32)"))


def manifest(kind, *tables, mode="copy"):
    return SourceManifest(name="shop", dbt_tag="shop", tables=tables, kind=kind, mode=mode, connection_env="SHOP")


def test_raw_tables_and_live_database_are_named_after_the_source():
    source = manifest("postgres", TableSpec("orders"))
    assert source_engines.raw_table(source, source.tables[0]) == "shop__orders"
    assert source_engines.live_database(source) == "src_shop"


@pytest.mark.parametrize(
    ("kind", "table", "expected"),
    [
        ("postgres", TableSpec("orders", source="Orders"), "postgresql(shop, table = 'Orders')"),
        ("mysql", TableSpec("orders"), "mysql(shop, table = 'orders')"),
        (
            "mongodb",
            TableSpec("orders", source="shop_orders", columns=COLUMNS),
            "mongodb(shop, collection = 'shop_orders', structure = '`order_id` String, `quantity` Nullable(Int32)')",
        ),
        ("files", TableSpec("orders", source="exports/orders.csv", format="csv"),
         "s3(shop, filename = 'exports/orders.csv', format = 'CSVWithNames')"),
        (
            "files",
            TableSpec("orders", source="orders.parquet", format="parquet", columns=COLUMNS),
            "s3(shop, filename = 'orders.parquet', format = 'Parquet', "
            "structure = '`order_id` String, `quantity` Nullable(Int32)')",
        ),
    ],
)
def test_copy_reads_each_kind_through_its_table_function(kind, table, expected):
    assert source_engines.table_function(manifest(kind, table), table) == expected


def test_huggingface_sources_have_no_table_function():
    table = TableSpec("orders", file="orders.parquet", format="parquet", expected_rows=1)
    with pytest.raises(ValueError, match="huggingface"):
        source_engines.table_function(manifest("huggingface", table), table)


@pytest.mark.parametrize(("kind", "engine"), [("postgres", "PostgreSQL"), ("mysql", "MySQL")])
def test_live_database_kinds_attach_one_database_engine(kind, engine):
    source = manifest(kind, TableSpec("orders"), TableSpec("items"), mode="live")
    assert source_engines.live_statements(source) == [
        f"CREATE DATABASE IF NOT EXISTS `src_shop` ENGINE = {engine}(shop)",
    ]


def test_live_mongodb_declares_a_table_engine_per_collection():
    source = manifest("mongodb", TableSpec("orders", source="shop_orders", columns=COLUMNS), mode="live")
    assert source_engines.live_statements(source) == [
        "CREATE DATABASE IF NOT EXISTS `src_shop`",
        "CREATE OR REPLACE TABLE `src_shop`.`orders` (`order_id` String, `quantity` Nullable(Int32)) "
        "ENGINE = MongoDB(shop, collection = 'shop_orders')",
    ]


def test_live_files_infer_columns_unless_declared():
    source = manifest(
        "files",
        TableSpec("orders", source="orders.csv", format="csv"),
        TableSpec("items", source="items.parquet", format="parquet", columns=COLUMNS[:1]),
        mode="live",
    )
    assert source_engines.live_statements(source) == [
        "CREATE DATABASE IF NOT EXISTS `src_shop`",
        "CREATE OR REPLACE TABLE `src_shop`.`orders` ENGINE = S3(shop, filename = 'orders.csv', format = 'CSVWithNames')",
        "CREATE OR REPLACE TABLE `src_shop`.`items` (`order_id` String) "
        "ENGINE = S3(shop, filename = 'items.parquet', format = 'Parquet')",
    ]


def test_relations_point_dbt_at_raw_copies_or_live_tables():
    tables = (TableSpec("orders", source="Orders"), TableSpec("items"))
    assert source_engines.relations(manifest("postgres", *tables)) == {
        "orders": "`raw`.`shop__orders`",
        "items": "`raw`.`shop__items`",
    }
    # A database engine shows each table under its source name.
    assert source_engines.relations(manifest("postgres", *tables, mode="live")) == {
        "orders": "`src_shop`.`Orders`",
        "items": "`src_shop`.`items`",
    }
    mongodb = manifest("mongodb", TableSpec("orders", source="shop_orders", columns=COLUMNS), mode="live")
    assert source_engines.relations(mongodb) == {"orders": "`src_shop`.`orders`"}


def test_huggingface_sources_are_never_live():
    table = TableSpec("orders", file="orders.parquet", format="parquet", expected_rows=1)
    with pytest.raises(ValueError, match="live"):
        source_engines.live_statements(manifest("huggingface", table, mode="live"))


def test_repository_fixture_manifests_generate_sql_without_credentials():
    for name in ("fixture_postgres", "fixture_mysql", "fixture_mongodb", "fixture_files"):
        source = load_manifest(name)
        live = SourceManifest(**{**source.__dict__, "mode": "live"})
        statements = [*source_engines.live_statements(live), *(source_engines.table_function(source, t) for t in source.tables)]
        assert all(name in statement for statement in statements)
        assert not any("password" in statement.lower() for statement in statements)
        assert set(source_engines.relations(source)) == {"widgets", "sales", "refunds"}
