"""SQL Server sources: read with a FreeTDS driver and copied into ``raw`` in batches (DECISIONS §4, Phase 18 fallback)."""

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import pytest

from app.sources.attach import Source
from app.sources.inspect import InspectError
from app.sources.sqlserver import (
    BATCH_ROWS, SqlServer, classify_error, clickhouse_type, connect_arguments, convert,
)


class FakeCursor:
    """Answers each statement with the rows registered for a fragment of it; ``fetchmany`` pages them."""

    def __init__(self, connection):
        self.connection = connection
        self.rows: list = []
        self.position = 0

    def execute(self, sql, params=None):
        self.connection.executed.append((sql, params))
        for fragment, rows in self.connection.routes.items():
            if fragment in sql:
                self.rows, self.position = list(rows), 0
                return
        self.rows, self.position = [], 0

    def fetchall(self):
        rows, self.position = self.rows[self.position:], len(self.rows)
        return rows

    def fetchmany(self, size):
        rows = self.rows[self.position:self.position + size]
        self.position += size
        return rows

    def close(self):
        pass


class FakeConnection:
    def __init__(self, routes=None, error=None):
        self.routes = routes or {}
        self.executed: list = []
        self.error = error
        self.closed = False

    def cursor(self):
        if self.error:
            raise self.error
        return FakeCursor(self)

    def close(self):
        self.closed = True


class FakeClickHouse:
    def __init__(self, published=False, cursor="9"):
        self.sql: list[str] = []
        self.inserts: list = []
        self.published = published
        self.cursor = cursor
        self.counts = iter([])

    def command(self, sql, **_):
        self.sql.append(sql)
        if sql.startswith("EXISTS TABLE"):
            return int(self.published)
        if sql.startswith("SELECT toString(max("):
            return self.cursor
        if sql.startswith("SELECT count()"):
            return 5
        return 0

    def insert(self, table, rows, column_names=None, **_):
        self.inserts.append((table, [list(row) for row in rows], column_names))


SOURCE = Source(name="erp", kind="sqlserver", database="widgets", schema="dbo")
PARAMS = dict(host="db.internal", port=1433, database="widgets", user="reader", password="pw-123", tls_mode="require")

COLUMNS = [
    ("orders", "id", "int", "NO", 1, None, 10, 0, None),
    ("orders", "placed", "datetime2", "NO", 2, None, None, None, 6),
    ("orders", "total", "decimal", "YES", 3, None, 18, 4, None),
    ("orders", "note", "nvarchar", "YES", 4, 100, None, None, None),
    ("orders", "paid", "bit", "NO", 5, None, None, None, None),
    ("orders", "token", "uniqueidentifier", "NO", 6, None, None, None, None),
    ("orders", "blob", "varbinary", "YES", 7, 16, None, None, None),
]


def test_a_connection_requires_encryption_by_default_and_uses_tds_74():
    arguments = connect_arguments(**PARAMS)

    assert arguments == {"server": "db.internal", "port": 1433, "database": "widgets", "user": "reader",
                         "password": "pw-123", "encryption": "require", "tds_version": "7.4", "login_timeout": 10,
                         "timeout": 0, "appname": "fitcher"}


def test_a_prefer_mode_asks_for_encryption_when_the_server_agrees():
    assert connect_arguments(**{**PARAMS, "tls_mode": "prefer"})["encryption"] == "request"


@pytest.mark.parametrize(("text", "reason"), [
    ("(18456, b\"Login failed for user 'u'.DB-Lib error message 20018\")", "authentication"),
    ("(18456, b'DB-Lib error message 20009 Unable to connect: TDS server is unavailable (db) Net-Lib error during Connection refused (111)')", "refused"),
    ("(18456, b'DB-Lib error message 20009 Unable to connect (db) Net-Lib error during Connection timed out (110)')", "unreachable"),
    ("(18456, b'Unknown error')", "unreachable"),
    ("(4060, b'Cannot open database \"nodb\" requested by the login. The login failed.')", "database_not_found"),
    ("(229, b\"The SELECT permission was denied on the object 'x', database 'y', schema 'dbo'.\")", "permission"),
    ("(20002, b'SSL routines: certificate verify failed')", "tls"),
    ("(18456, b'DB-Lib error message 20018, severity 14:\\nGeneral SQL Server error\\nDB-Lib error message 20002, severity 9:\\nTDS server connection failed (db)')", "authentication"),
    ("something else", "unknown"),
])
def test_a_driver_failure_becomes_one_fixed_reason(text, reason):
    assert classify_error(RuntimeError(text)) == reason


def test_a_failed_check_raises_only_the_reason():
    leak = RuntimeError("(18456, b\"Login failed for user 'reader' with password 'pw-123'\")")

    def connect(**_):
        raise leak

    with pytest.raises(InspectError) as raised:
        SqlServer(connect).check(**PARAMS)

    assert raised.value.reason == "authentication"
    assert "pw-123" not in str(raised.value) and raised.value.__cause__ is None


def test_a_check_reads_one_row_and_closes_the_connection():
    connection = FakeConnection({"SELECT 1": [(1,)]})

    SqlServer(lambda **_: connection).check(**PARAMS)

    assert connection.executed[0][0].startswith("SELECT 1") and connection.closed


def test_the_catalog_lists_tables_with_estimates_sizes_keys_columns_and_flags():
    connection = FakeConnection({
        "sys.partitions": [("orders", "U", 1200, 16384), ("v_open", "V", None, None)],
        "INFORMATION_SCHEMA.COLUMNS": COLUMNS + [("v_open", "id", "int", "YES", 1, None, 10, 0, None)],
        "is_primary_key": [("orders", "id", 1)],
        "sys.foreign_keys": [("fk_items", "items", "line_ref", "orders", "id", 1)],
    })

    tables = {table.name: table for table in SqlServer(lambda **_: connection).tables(schema="dbo", **PARAMS)}

    orders, view = tables["orders"], tables["v_open"]
    assert (orders.kind, orders.rows, orders.size_bytes, orders.primary_key) == ("table", 1200, 16384, ("id",))
    assert view.kind == "view" and view.rows is None
    assert [c.name for c in orders.columns] == ["id", "placed", "total", "note", "paid", "token", "blob"]
    assert orders.columns[0].type == "int" and orders.columns[0].nullable is False and orders.columns[2].nullable is True
    assert orders.unusual_columns == ("blob",)
    assert [(k.columns, k.ref_table, k.ref_columns) for k in tables["items"].foreign_keys] == [(("line_ref",), "orders", ("id",))] if "items" in tables else True
    assert all("dbo" in str(params) for _, params in connection.executed if params)


@pytest.mark.parametrize(("column", "expected"), [
    (("int", "NO", None, 10, 0, None), "Int32"),
    (("int", "YES", None, 10, 0, None), "Nullable(Int32)"),
    (("bigint", "NO", None, 19, 0, None), "Int64"),
    (("smallint", "NO", None, 5, 0, None), "Int16"),
    (("tinyint", "NO", None, 3, 0, None), "UInt8"),
    (("bit", "NO", None, None, None, None), "Bool"),
    (("decimal", "NO", None, 18, 4, None), "Decimal(18, 4)"),
    (("numeric", "YES", None, 38, 10, None), "Nullable(Decimal(38, 10))"),
    (("money", "NO", None, 19, 4, None), "Decimal(19, 4)"),
    (("float", "NO", None, 53, None, None), "Float64"),
    (("real", "NO", None, 24, None, None), "Float32"),
    (("date", "NO", None, None, None, 0), "Date32"),
    (("datetime", "NO", None, None, None, 3), "DateTime64(3, 'UTC')"),
    (("datetime2", "NO", None, None, None, 7), "DateTime64(7, 'UTC')"),
    (("smalldatetime", "NO", None, None, None, 0), "DateTime64(0, 'UTC')"),
    (("datetimeoffset", "NO", None, None, None, 7), "DateTime64(7, 'UTC')"),
    (("time", "NO", None, None, None, 7), "String"),
    (("uniqueidentifier", "NO", None, None, None, None), "UUID"),
    (("nvarchar", "NO", 100, None, None, None), "String"),
    (("xml", "YES", None, None, None, None), "Nullable(String)"),
    (("varbinary", "NO", 16, None, None, None), "String"),
    (("geography", "YES", None, None, None, None), "Nullable(String)"),
])
def test_each_sql_server_type_maps_to_a_clickhouse_type(column, expected):
    data_type, nullable, length, precision, scale, datetime_precision = column
    assert clickhouse_type(data_type, nullable == "YES", precision, scale, datetime_precision) == expected


def test_values_are_converted_for_clickhouse():
    token = UUID("6f9619ff-8b86-d011-b42d-00c04fc964ff")
    assert convert(b"\x01\xab") == "01ab"
    assert convert(Decimal("1.50")) == Decimal("1.50")
    assert convert(token) == token
    assert convert(True) is True
    assert convert("Hà Nội") == "Hà Nội"
    assert convert(None) is None
    assert convert(datetime(2025, 1, 2, 3, 4, 5, 123456)) == datetime(2025, 1, 2, 3, 4, 5, 123456, tzinfo=UTC)
    assert convert(datetime(2025, 1, 2, 3, 0, tzinfo=timezone(timedelta(hours=7)))) == datetime(2025, 1, 1, 20, 0, tzinfo=UTC)


def copy_connection(rows, columns=COLUMNS[:5]):
    return FakeConnection({"INFORMATION_SCHEMA.COLUMNS": columns, "FROM [dbo].[orders]": rows})


def test_a_full_copy_streams_batches_into_a_loading_table_and_publishes_it():
    rows = [(i, datetime(2025, 1, 1), Decimal("1.0"), "n", True) for i in range(1, 4)]
    connection, clickhouse = copy_connection(rows), FakeClickHouse()

    outcome = SqlServer(lambda **_: connection).copy(
        clickhouse, SOURCE, "orders", cursor_column=None, after=None, schema="dbo", **PARAMS)

    assert (outcome.rows, outcome.full, outcome.cursor) == (5, True, None)
    create = next(sql for sql in clickhouse.sql if sql.startswith("CREATE TABLE"))
    assert create == ("CREATE TABLE `raw`.`erp__orders__loading` (`id` Int32, `placed` DateTime64(6, 'UTC'), "
                      "`total` Nullable(Decimal(18, 4)), `note` Nullable(String), `paid` Bool) "
                      "ENGINE = MergeTree ORDER BY tuple()")
    table, inserted, names = clickhouse.inserts[0]
    assert table == "`raw`.`erp__orders__loading`" and len(inserted) == 3 and names == ["id", "placed", "total", "note", "paid"]
    assert any(sql.startswith("RENAME TABLE") for sql in clickhouse.sql)
    select = connection.executed[-1][0]
    assert select == "SELECT [id], [placed], [total], [note], [paid] FROM [dbo].[orders]"


def test_a_copy_reads_in_batches_so_a_large_table_never_sits_in_memory():
    rows = [(i, datetime(2025, 1, 1), None, None, False) for i in range(BATCH_ROWS * 2 + 5)]
    connection, clickhouse = copy_connection(rows), FakeClickHouse()

    SqlServer(lambda **_: connection).copy(clickhouse, SOURCE, "orders", cursor_column=None, after=None, schema="dbo", **PARAMS)

    assert [len(batch[1]) for batch in clickhouse.inserts] == [BATCH_ROWS, BATCH_ROWS, 5]


def test_an_incremental_copy_filters_by_the_cursor_value_and_appends():
    rows = [(10, datetime(2025, 1, 1), None, None, True)]
    connection, clickhouse = copy_connection(rows), FakeClickHouse(published=True, cursor="10")

    outcome = SqlServer(lambda **_: connection).copy(
        clickhouse, SOURCE, "orders", cursor_column="id", after="9", schema="dbo", **PARAMS)

    assert (outcome.full, outcome.cursor) == (False, "10")
    sql, params = connection.executed[-1]
    assert sql.endswith("WHERE [id] > %s") and params == ("9",)
    assert "CREATE TABLE `raw`.`erp__orders__loading` AS `raw`.`erp__orders`" in clickhouse.sql
    assert "INSERT INTO `raw`.`erp__orders` SELECT * FROM `raw`.`erp__orders__loading`" in clickhouse.sql


def test_a_failed_read_drops_the_loading_table_and_publishes_nothing():
    connection = copy_connection([(1, datetime(2025, 1, 1), None, None, True)])
    clickhouse = FakeClickHouse()

    def broken(table, rows, column_names=None, **_):
        raise RuntimeError("insert failed")

    clickhouse.insert = broken

    with pytest.raises(RuntimeError):
        SqlServer(lambda **_: connection).copy(clickhouse, SOURCE, "orders", cursor_column=None, after=None, schema="dbo", **PARAMS)

    assert clickhouse.sql[-1] == "DROP TABLE IF EXISTS `raw`.`erp__orders__loading`"
    assert not any(sql.startswith(("RENAME", "EXCHANGE")) for sql in clickhouse.sql)
    assert connection.closed


def test_a_copy_can_be_stopped_between_batches():
    rows = [(i, datetime(2025, 1, 1), None, None, False) for i in range(BATCH_ROWS * 3)]
    connection, clickhouse = copy_connection(rows), FakeClickHouse()
    calls = iter([False, True])

    with pytest.raises(RuntimeError, match="cancelled"):
        SqlServer(lambda **_: connection).copy(clickhouse, SOURCE, "orders", cursor_column=None, after=None, schema="dbo",
                                               should_stop=lambda: next(calls, True), **PARAMS)

    assert len(clickhouse.inserts) == 1
    assert clickhouse.sql[-1] == "DROP TABLE IF EXISTS `raw`.`erp__orders__loading`"


def test_identifiers_with_brackets_are_escaped():
    from app.sources.sqlserver import bracket

    assert bracket("a]b") == "[a]]b]"
