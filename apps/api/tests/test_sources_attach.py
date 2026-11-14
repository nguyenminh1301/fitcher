"""Copying and attaching a source's tables through ClickHouse, shared by the jobs and the api (DECISIONS §4)."""

import pytest

from app.sources import attach
from app.sources.attach import Column, Source, Table


class FakeClient:
    """Records SQL; ``results`` maps a substring of a statement to what ``command`` answers for it."""

    def __init__(self, results=None, fail_on=None):
        self.sql: list[str] = []
        self.results = results or {}
        self.fail_on = fail_on

    def command(self, sql):
        self.sql.append(sql)
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError("source unreachable")
        for fragment, answer in self.results.items():
            if fragment in sql:
                return answer(sql) if callable(answer) else answer
        return 0


def source(*tables, kind="postgres"):
    return Source(name="shop", kind=kind, tables=tables)


ORDERS = Table("orders")


def test_staging_a_copy_reads_the_table_function_into_a_loading_table_and_counts_it():
    client = FakeClient({"SELECT count()": 7})

    assert attach.stage_copy(client, source(ORDERS), ORDERS) == 7
    assert client.sql[0] == "DROP TABLE IF EXISTS `raw`.`shop__orders__loading`"
    assert client.sql[1] == (
        "CREATE TABLE `raw`.`shop__orders__loading` ENGINE = MergeTree ORDER BY tuple() "
        "AS SELECT * FROM postgresql(shop, table = 'orders')"
    )
    assert client.sql[2] == "SELECT count() FROM `raw`.`shop__orders__loading`"


def test_a_failed_staging_drops_the_loading_table_and_raises():
    client = FakeClient(fail_on="CREATE TABLE")

    with pytest.raises(RuntimeError, match="unreachable"):
        attach.stage_copy(client, source(ORDERS), ORDERS)
    assert client.sql[-1] == "DROP TABLE IF EXISTS `raw`.`shop__orders__loading`"


def test_publishing_renames_a_first_copy_and_exchanges_a_later_one():
    first = FakeClient({"EXISTS TABLE": 0})
    attach.publish_copy(first, source(ORDERS), ORDERS)
    assert first.sql[-1] == "RENAME TABLE `raw`.`shop__orders__loading` TO `raw`.`shop__orders`"

    later = FakeClient({"EXISTS TABLE": 1})
    attach.publish_copy(later, source(ORDERS), ORDERS)
    assert later.sql[-2:] == [
        "EXCHANGE TABLES `raw`.`shop__orders__loading` AND `raw`.`shop__orders`",
        "DROP TABLE `raw`.`shop__orders__loading`",
    ]


def test_a_reload_copy_publishes_only_after_the_count_and_reports_the_cursor():
    client = FakeClient({"SELECT count()": 5, "EXISTS TABLE": 0, "SELECT toString(max(": "41"})

    outcome = attach.copy_table(client, source(ORDERS), ORDERS, cursor_column="id", after=None)

    assert (outcome.rows, outcome.cursor, outcome.full) == (5, "41", True)
    assert any(statement.startswith("RENAME TABLE") for statement in client.sql)
    assert "SELECT toString(max(`id`)) FROM `raw`.`shop__orders`" in client.sql


def test_a_copy_without_a_cursor_column_reports_no_cursor():
    client = FakeClient({"SELECT count()": 5, "EXISTS TABLE": 0})

    outcome = attach.copy_table(client, source(ORDERS), ORDERS, cursor_column=None, after=None)

    assert (outcome.rows, outcome.cursor, outcome.full) == (5, None, True)
    assert not any("max(" in statement for statement in client.sql)


def test_an_incremental_copy_reads_only_rows_above_the_last_value_and_appends_them():
    counts = iter([10, 13])
    client = FakeClient({"EXISTS TABLE": 1, "SELECT count()": lambda sql: next(counts), "toString(max(": "44"})

    outcome = attach.copy_table(client, source(ORDERS), ORDERS, cursor_column="id", after="41")

    assert (outcome.rows, outcome.cursor, outcome.full) == (3, "44", False)
    assert client.sql[1] == "SELECT count() FROM `raw`.`shop__orders`"
    assert client.sql[2] == "DROP TABLE IF EXISTS `raw`.`shop__orders__loading`"
    stage = next(statement for statement in client.sql if statement.startswith("CREATE TABLE"))
    assert stage == (
        "CREATE TABLE `raw`.`shop__orders__loading` AS `raw`.`shop__orders`"
    )
    read = next(statement for statement in client.sql if statement.startswith("INSERT INTO `raw`.`shop__orders__loading`"))
    assert read == (
        "INSERT INTO `raw`.`shop__orders__loading` SELECT * FROM postgresql(shop, table = 'orders') "
        "WHERE `id` > '41'"
    )
    appended = client.sql.index("INSERT INTO `raw`.`shop__orders` SELECT * FROM `raw`.`shop__orders__loading`")
    assert client.sql[appended + 1] == "DROP TABLE IF EXISTS `raw`.`shop__orders__loading`"


def test_a_failed_incremental_copy_leaves_the_copy_untouched_and_drops_its_staging_table():
    client = FakeClient({"EXISTS TABLE": 1, "SELECT count()": 10}, fail_on="WHERE `id` > '41'")

    with pytest.raises(RuntimeError):
        attach.copy_table(client, source(ORDERS), ORDERS, cursor_column="id", after="41")

    assert not any(statement.startswith("INSERT INTO `raw`.`shop__orders` ") for statement in client.sql)
    assert client.sql[-1] == "DROP TABLE IF EXISTS `raw`.`shop__orders__loading`"


def test_a_cursor_value_is_escaped_into_the_filter():
    client = FakeClient({"EXISTS TABLE": 1, "SELECT count()": 0, "toString(max(": "x"})

    attach.copy_table(client, source(ORDERS), ORDERS, cursor_column="id", after="a'b\\c")

    assert any(statement.endswith("WHERE `id` > 'a\\'b\\\\c'") for statement in client.sql)


def test_attaching_live_defines_the_database_and_counts_each_table():
    client = FakeClient({"SELECT count()": 9})
    shop = source(ORDERS, Table("items", source_name="order_items"))

    counts = attach.attach_live(client, shop)

    assert client.sql[0] == "CREATE DATABASE IF NOT EXISTS `src_shop` ENGINE = PostgreSQL(shop)"
    assert counts == {"orders": 9, "items": 9}
    assert "SELECT count() FROM `src_shop`.`order_items`" in client.sql


def test_dropping_a_source_removes_its_database_and_its_copies():
    client = FakeClient()

    attach.drop_source(client, source(ORDERS, Table("items")))

    assert client.sql == [
        "DROP DATABASE IF EXISTS `src_shop`",
        "DROP TABLE IF EXISTS `raw`.`shop__orders`",
        "DROP TABLE IF EXISTS `raw`.`shop__orders__loading`",
        "DROP TABLE IF EXISTS `raw`.`shop__items`",
        "DROP TABLE IF EXISTS `raw`.`shop__items__loading`",
    ]


def test_a_source_name_must_be_a_lower_case_identifier():
    for good in ("shop", "erp_2", "a"):
        assert attach.valid_name(good)
    for bad in ("", "Shop", "2shop", "shop-db", "a" * 41, "shop name", "raw"):
        assert not attach.valid_name(bad), bad


def test_columns_are_declared_for_a_file_copy():
    table = Table("orders", source_name="orders.csv", columns=(Column("id", "Int64"),), format="csv")
    assert attach.table_function(source(table, kind="files"), table) == (
        "s3(shop, filename = 'orders.csv', format = 'CSVWithNames', structure = '`id` Int64')"
    )


def test_a_source_of_the_sources_page_names_its_database_and_schema_where_the_collection_is_used():
    shop = Source(name="shop", kind="postgres", tables=(ORDERS,), database="erp", schema="sales")

    assert attach.table_function(shop, ORDERS) == (
        "postgresql(shop, database = 'erp', schema = 'sales', table = 'orders')"
    )
    assert attach.live_statements(shop) == [
        "CREATE DATABASE IF NOT EXISTS `src_shop` ENGINE = PostgreSQL(shop, database = 'erp', schema = 'sales')",
    ]


def test_a_mysql_source_names_only_its_database():
    shop = Source(name="shop", kind="mysql", tables=(ORDERS,), database="erp", schema="ignored")

    assert attach.table_function(shop, ORDERS) == "mysql(shop, database = 'erp', table = 'orders')"
    assert attach.live_statements(shop) == [
        "CREATE DATABASE IF NOT EXISTS `src_shop` ENGINE = MySQL(shop, database = 'erp')",
    ]
