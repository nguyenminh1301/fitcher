"""Testing a connection and listing a source's tables through ClickHouse, with no database driver in the api."""

import pytest

from app.sources.attach import Source
from app.sources.inspect import REASONS, InspectError, Inspector, classify_error

PG = Source(name="shop", kind="postgres", database="erp", schema="sales")
MY = Source(name="shop", kind="mysql", database="erp")


class FakeClient:
    """Answers ``query`` with the rows registered for the first fragment found in the statement."""

    def __init__(self, routes=None, error=None):
        self.routes = routes or {}
        self.error = error
        self.sql: list[str] = []

    def query(self, sql, **_):
        self.sql.append(sql)
        if self.error:
            raise self.error
        for fragment, rows in self.routes.items():
            if fragment in sql:
                return type("Result", (), {"result_rows": rows})()
        return type("Result", (), {"result_rows": []})()


PG_ROUTES = {
    "pg_class": [("orders", "r", 1200.0, 50, "100"), ("order_items", "r", -1.0, 0, "101"), ("v_open", "v", 0.0, 0, "102")],
    "pg_stat_user_tables": [("order_items", 40000)],
    "table = 'columns'": [
        ("orders", "id", "integer", "int4", "NO", 1), ("orders", "tags", "ARRAY", "_text", "YES", 2),
        ("orders", "meta", "jsonb", "jsonb", "YES", 3), ("order_items", "order_id", "integer", "int4", "NO", 1),
        ("v_open", "id", "integer", "int4", "YES", 1),
    ],
    "pg_constraint": [("orders_pkey", "p", "100", "0", [1], []), ("items_order_fkey", "f", "101", "100", [1], [1])],
    "pg_attribute": [("100", 1, "id"), ("101", 1, "order_id")],
}


def test_a_postgres_table_list_carries_estimates_sizes_keys_and_flags():
    tables = {table.name: table for table in Inspector(FakeClient(PG_ROUTES)).tables(PG)}

    orders, items, view = tables["orders"], tables["order_items"], tables["v_open"]
    assert (orders.kind, orders.rows, orders.size_bytes) == ("table", 1200, 50 * 8192)
    assert items.rows == 40000, "a table never analysed reports -1, so the live-tuple statistic is used"
    assert view.kind == "view" and view.rows is None and view.size_bytes is None
    assert orders.primary_key == ("id",) and items.primary_key == ()
    assert [(fk.columns, fk.ref_table, fk.ref_columns) for fk in items.foreign_keys] == [(("order_id",), "orders", ("id",))]
    assert orders.unusual_columns == ("tags", "meta")
    assert [column.name for column in orders.columns] == ["id", "tags", "meta"]
    assert orders.columns[0].nullable is False and orders.columns[1].nullable is True


def test_the_postgres_catalog_is_read_through_the_collection_with_the_schema_as_a_bound_literal():
    client = FakeClient(PG_ROUTES)
    Inspector(client).tables(Source(name="shop", kind="postgres", database="erp", schema="o'neil"))

    assert all("postgresql(shop, database = 'erp'," in sql for sql in client.sql)
    assert any("n.nspname = 'o\\'neil'" in sql for sql in client.sql)
    assert any("schema = 'information_schema', table = 'columns'" in sql for sql in client.sql)


MY_ROUTES = {
    "table = 'TABLES'": [("orders", "BASE TABLE", 1200, 16384, 1000), ("v_open", "VIEW", None, None, None)],
    "table = 'COLUMNS'": [
        ("orders", "id", "int", "int", "NO", 1), ("orders", "status", "enum", "enum('a','b')", "YES", 2),
        ("orders", "geo", "point", "point", "YES", 3),
    ],
    "table = 'KEY_COLUMN_USAGE'": [
        ("PRIMARY", "orders", "id", 1, None, None),
        ("fk_cust", "orders", "customer_id", 1, "customers", "id"),
    ],
}


def test_a_mysql_table_list_uses_the_information_schema():
    tables = {table.name: table for table in Inspector(FakeClient(MY_ROUTES)).tables(MY)}

    orders = tables["orders"]
    assert (orders.kind, orders.rows, orders.size_bytes) == ("table", 1200, 17384)
    assert tables["v_open"].kind == "view" and tables["v_open"].rows is None
    assert orders.primary_key == ("id",)
    assert [(fk.columns, fk.ref_table, fk.ref_columns) for fk in orders.foreign_keys] == [
        (("customer_id",), "customers", ("id",))]
    assert orders.unusual_columns == ("status", "geo")


def test_a_mysql_source_reads_the_information_schema_database_and_filters_by_its_own():
    client = FakeClient(MY_ROUTES)
    Inspector(client).tables(MY)

    assert all("mysql(shop, database = 'information_schema'," in sql for sql in client.sql)
    assert all("TABLE_SCHEMA = 'erp'" in sql for sql in client.sql)


def test_a_postgres_connection_check_reads_one_catalog_row():
    client = FakeClient({"pg_namespace": [("sales",)]})

    Inspector(client).check(PG)

    assert "postgresql(shop, database = 'erp', schema = 'pg_catalog', table = 'pg_namespace')" in client.sql[0]


def test_a_mysql_check_finds_the_database_in_the_catalog_or_reports_it_missing():
    Inspector(FakeClient({"SCHEMATA": [("erp",)]})).check(MY)

    with pytest.raises(InspectError) as raised:
        Inspector(FakeClient({"SCHEMATA": []})).check(MY)
    assert raised.value.reason == "database_not_found"


@pytest.mark.parametrize(("text", "reason"), [
    ('Connection to `db:5432` failed with error: could not translate host name "db" to address: Name or service not known',
     "unreachable"),
    ("Connections to mysql failed: ERROR 2005 : mysqlxx::ConnectionFailed: Unknown server host 'db' (-2)", "unreachable"),
    ("connection to server at \"db\", port 5432 failed: timeout expired", "unreachable"),
    ("connection to server at \"db\" (10.0.0.1), port 1 failed: Connection refused", "refused"),
    ("ERROR 2002 : mysqlxx::ConnectionFailed: Can't connect to server on 'db' (115)", "refused"),
    ('FATAL:  password authentication failed for user "u"', "authentication"),
    ("ERROR 1045 : Access denied for user 'u'@'10.0.0.2' (using password: YES)", "authentication"),
    ("server does not support SSL, but SSL was required", "tls"),
    ("SSL error: certificate verify failed", "tls"),
    ('FATAL:  database "nope" does not exist', "database_not_found"),
    ("ERROR 1044 : Access denied for user 'u'@'%' to database 'nope'", "database_not_found"),
    ("ERROR 1049 : Unknown database 'nope'", "database_not_found"),
    ("pqxx::insufficient_privilege, e.what() = ERROR:  permission denied for table secret_t", "permission"),
    ("SELECT command denied to user 'u'@'%' for table 'orders'", "permission"),
    ("something nobody expected", "unknown"),
])
def test_a_driver_failure_becomes_one_fixed_reason(text, reason):
    assert classify_error(RuntimeError(text)) == reason
    assert reason in REASONS


def test_a_failed_check_raises_only_the_reason_never_the_driver_text():
    leaking = RuntimeError("Connections to mysql failed: u@10.0.0.9 password = 's3cret' ERROR 1045 : Access denied")

    with pytest.raises(InspectError) as raised:
        Inspector(FakeClient(error=leaking)).check(MY)

    assert raised.value.reason == "authentication"
    assert "s3cret" not in str(raised.value) and "10.0.0.9" not in str(raised.value)
    assert raised.value.__cause__ is None and raised.value.__suppress_context__


def test_the_reasons_are_the_fixed_set_of_the_plan_plus_unknown():
    assert set(REASONS) == {"unreachable", "refused", "authentication", "tls", "database_not_found", "permission",
                            "unknown"}
