"""Read SQL Server and copy its tables into ClickHouse ``raw`` (DECISIONS §4, Phase 18).

ClickHouse has no native SQL Server engine, and its ODBC bridge is not shipped in the 26.8 packages
(docs/eval/sql-server-source-report.md), so this kind is copy-only and the api reads the source itself with
``pymssql``, whose wheels bundle FreeTDS (LGPL; Microsoft's own driver is not shipped). The password is therefore a
secret of the app state (``source:<id>:password`` in the vault) and not a ClickHouse named collection: the one
exception to DECISIONS §4's rule that credentials live in ClickHouse.

Encryption is required by default (``encryption='require'``, which the server confirms in
``sys.dm_exec_connections``); this driver does not verify the server's certificate. The catalog is read with
``INFORMATION_SCHEMA`` and the ``sys`` views, and a copy streams rows in batches of ``BATCH_ROWS``, so a large table
never sits in the api's memory. A failure is one fixed reason and never the driver's text.
"""

from collections.abc import Callable
from datetime import UTC, datetime, time
from decimal import Decimal
import logging
import re
from uuid import UUID

from app.sources.attach import (
    CopyOutcome, Table, _cursor, loading_table, publish_raw_table, quote, raw_relation, raw_table,
)
from app.sources.inspect import CatalogColumn, ForeignKey, InspectError, TableInfo

logger = logging.getLogger(__name__)

BATCH_ROWS = 20_000
PAGE_BYTES = 8192
UNUSUAL_TYPES = frozenset({
    "xml", "geography", "geometry", "hierarchyid", "sql_variant", "binary", "varbinary", "image", "timestamp",
    "rowversion",
})
_INTEGERS = {"bigint": "Int64", "int": "Int32", "smallint": "Int16", "tinyint": "UInt8"}

_PATTERNS = (
    ("tls", re.compile(r"SSL|TLS|certificate|encrypt", re.IGNORECASE)),
    ("database_not_found", re.compile(r"Cannot open database|\(4060,", re.IGNORECASE)),
    ("authentication", re.compile(r"Login failed", re.IGNORECASE)),
    ("permission", re.compile(r"permission was denied|\(229,|\(262,|\(297,", re.IGNORECASE)),
    ("refused", re.compile(r"Connection refused", re.IGNORECASE)),
    ("unreachable", re.compile(
        r"timed out|TDS server is unavailable|Unknown error|Name or service not known|No route to host|"
        r"Network is unreachable|Unknown host", re.IGNORECASE)),
    # The server was reached and closed the login; FreeTDS often loses the "Login failed" or "Cannot open database"
    # message of the second attempt, so a wrong password and an unknown database look the same.
    ("authentication", re.compile(r"TDS server connection failed", re.IGNORECASE)),
)


def classify_error(error: BaseException) -> str:
    text = str(error)
    for reason, pattern in _PATTERNS:
        if pattern.search(text):
            return reason
    return "unknown"


def connect_arguments(*, host: str, port: int, database: str, user: str, password: str, tls_mode: str) -> dict:
    """The ``pymssql.connect`` arguments: TDS 7.4 and encryption required unless the user chose ``prefer``."""
    return {
        "server": host, "port": port, "database": database, "user": user, "password": password,
        "encryption": "request" if tls_mode == "prefer" else "require", "tds_version": "7.4", "login_timeout": 10,
        "timeout": 0, "appname": "fitcher",
    }


def bracket(identifier: str) -> str:
    return "[" + identifier.replace("]", "]]") + "]"


def clickhouse_type(data_type: str, nullable: bool, precision, scale, datetime_precision) -> str:
    """The ClickHouse type a SQL Server column is copied as; types without a counterpart are copied as text."""
    kind = data_type.lower()
    if kind in _INTEGERS:
        base = _INTEGERS[kind]
    elif kind == "bit":
        base = "Bool"
    elif kind in ("decimal", "numeric", "money", "smallmoney"):
        base = f"Decimal({int(precision)}, {int(scale)})"
    elif kind == "float":
        base = "Float64"
    elif kind == "real":
        base = "Float32"
    elif kind == "date":
        base = "Date32"
    elif kind in ("datetime", "datetime2", "smalldatetime", "datetimeoffset"):
        # Always UTC: a wall-clock value is stored as it is read, and an offset value as its UTC moment.
        base = f"DateTime64({int(datetime_precision or 0)}, 'UTC')"
    elif kind == "uniqueidentifier":
        base = "UUID"
    else:
        base = "String"
    return f"Nullable({base})" if nullable else base


def convert(value):
    """A value as ``insert`` takes it: bytes as hex, a time of day as text, a moment in UTC, the rest unchanged.

    A naive datetime is the wall clock SQL Server stores; marking it UTC keeps the driver from shifting it by the
    api's own time zone, which would move every value by the offset.
    """
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    if isinstance(value, (Decimal, UUID)):
        return value
    return value


class SqlServer:
    def __init__(self, connect: Callable[..., object] | None = None):
        self._connect = connect

    def _open(self, params: dict):
        connect = self._connect
        if connect is None:
            import pymssql

            connect = pymssql.connect
        try:
            return connect(**connect_arguments(**params))
        except Exception as error:  # noqa: BLE001 - the driver text can name hosts, users and the password
            raise InspectError(classify_error(error)) from None

    def check(self, **params) -> None:
        connection = self._open(params)
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchall()
        except Exception as error:  # noqa: BLE001
            raise InspectError(classify_error(error)) from None
        finally:
            connection.close()

    def _query(self, cursor, sql: str, parameters: tuple = ()) -> list[tuple]:
        try:
            cursor.execute(sql, parameters or None)
            return [tuple(row) for row in cursor.fetchall()]
        except Exception as error:  # noqa: BLE001
            raise InspectError(classify_error(error)) from None

    def tables(self, *, schema: str, **params) -> list[TableInfo]:
        connection = self._open(params)
        try:
            cursor = connection.cursor()
            objects = self._query(cursor, (
                "SELECT o.name, o.type, SUM(CASE WHEN p.index_id IN (0, 1) THEN p.rows END) AS row_count, "
                f"SUM(a.total_pages) * {PAGE_BYTES} AS size_bytes FROM sys.objects AS o "
                "INNER JOIN sys.schemas AS s ON s.schema_id = o.schema_id "
                "LEFT JOIN sys.partitions AS p ON p.object_id = o.object_id "
                "LEFT JOIN sys.allocation_units AS a ON a.container_id = p.partition_id "
                "WHERE s.name = %s AND o.type IN ('U', 'V') GROUP BY o.name, o.type ORDER BY o.name"), (schema,))
            columns = self._query(cursor, (
                "SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, IS_NULLABLE, ORDINAL_POSITION, CHARACTER_MAXIMUM_LENGTH, "
                "NUMERIC_PRECISION, NUMERIC_SCALE, DATETIME_PRECISION FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = %s ORDER BY TABLE_NAME, ORDINAL_POSITION"), (schema,))
            keys = self._query(cursor, (
                "SELECT t.name, c.name, ic.key_ordinal FROM sys.indexes AS i "
                "INNER JOIN sys.index_columns AS ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id "
                "INNER JOIN sys.columns AS c ON c.object_id = ic.object_id AND c.column_id = ic.column_id "
                "INNER JOIN sys.tables AS t ON t.object_id = i.object_id "
                "INNER JOIN sys.schemas AS s ON s.schema_id = t.schema_id "
                "WHERE i.is_primary_key = 1 AND s.name = %s ORDER BY t.name, ic.key_ordinal"), (schema,))
            references = self._query(cursor, (
                "SELECT fk.name, pt.name, pc.name, rt.name, rc.name, fkc.constraint_column_id "
                "FROM sys.foreign_keys AS fk "
                "INNER JOIN sys.foreign_key_columns AS fkc ON fkc.constraint_object_id = fk.object_id "
                "INNER JOIN sys.tables AS pt ON pt.object_id = fkc.parent_object_id "
                "INNER JOIN sys.columns AS pc ON pc.object_id = fkc.parent_object_id AND pc.column_id = fkc.parent_column_id "
                "INNER JOIN sys.tables AS rt ON rt.object_id = fkc.referenced_object_id "
                "INNER JOIN sys.columns AS rc ON rc.object_id = fkc.referenced_object_id AND rc.column_id = fkc.referenced_column_id "
                "INNER JOIN sys.schemas AS s ON s.schema_id = pt.schema_id WHERE s.name = %s "
                "ORDER BY pt.name, fk.name, fkc.constraint_column_id"), (schema,))
        finally:
            connection.close()
        by_table: dict[str, list[CatalogColumn]] = {}
        unusual: dict[str, list[str]] = {}
        for table, column, data_type, nullable, position, *_ in columns:
            by_table.setdefault(table, []).append(CatalogColumn(column, data_type, str(nullable).upper() == "YES", int(position)))
            if data_type.lower() in UNUSUAL_TYPES:
                unusual.setdefault(table, []).append(column)
        primary: dict[str, list[str]] = {}
        for table, column, _ in keys:
            primary.setdefault(table, []).append(column)
        foreign: dict[tuple[str, str], tuple[list[str], str, list[str]]] = {}
        for name, table, column, ref_table, ref_column, _ in references:
            entry = foreign.setdefault((table, name), ([], ref_table, []))
            entry[0].append(column)
            entry[2].append(ref_column)
        result = []
        for name, kind, rows, size in objects:
            is_view = kind.strip() == "V"
            result.append(TableInfo(
                name=name, kind="view" if is_view else "table", rows=None if is_view or rows is None else int(rows),
                size_bytes=None if is_view or size is None else int(size), columns=tuple(by_table.get(name, ())),
                primary_key=tuple(primary.get(name, ())),
                foreign_keys=tuple(ForeignKey(tuple(c), ref, tuple(rc)) for (t, _), (c, ref, rc) in foreign.items() if t == name),
                unusual_columns=tuple(unusual.get(name, ()))))
        return result

    def copy(self, clickhouse, source, table: str, *, cursor_column: str | None, after: str | None, schema: str,
             should_stop: Callable[[], bool] | None = None, **params) -> CopyOutcome:
        """Copy one table into ``raw``: all rows swapped in atomically, or only the rows above ``after`` appended."""
        spec = Table(table)
        target, loading = raw_relation(source, spec), loading_table(raw_table(source, spec))
        incremental = (cursor_column is not None and after is not None
                       and bool(int(clickhouse.command(f"EXISTS TABLE {target}"))))
        before = int(clickhouse.command(f"SELECT count() FROM {target}")) if incremental else 0
        connection = self._open(params)
        clickhouse.command(f"DROP TABLE IF EXISTS {loading}")
        try:
            cursor = connection.cursor()
            columns = self._query(cursor, (
                "SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, IS_NULLABLE, ORDINAL_POSITION, CHARACTER_MAXIMUM_LENGTH, "
                "NUMERIC_PRECISION, NUMERIC_SCALE, DATETIME_PRECISION FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s ORDER BY ORDINAL_POSITION"), (schema, table))
            names = [row[1] for row in columns]
            structure = ", ".join(
                f"{quote(row[1])} {clickhouse_type(row[2], str(row[3]).upper() == 'YES', row[6], row[7], row[8])}"
                for row in columns)
            if incremental:
                clickhouse.command(f"CREATE TABLE {loading} AS {target}")
            else:
                clickhouse.command(f"CREATE TABLE {loading} ({structure}) ENGINE = MergeTree ORDER BY tuple()")
            select = f"SELECT {', '.join(bracket(n) for n in names)} FROM {bracket(schema)}.{bracket(table)}"
            parameters: tuple = ()
            if incremental:
                select += f" WHERE {bracket(cursor_column)} > %s"
                parameters = (after,)
            cursor.execute(select, parameters or None)
            while True:
                if should_stop is not None and should_stop():
                    raise RuntimeError("the copy was cancelled")
                rows = cursor.fetchmany(BATCH_ROWS)
                if not rows:
                    break
                clickhouse.insert(loading, [tuple(convert(value) for value in row) for row in rows], column_names=names)
            if incremental:
                clickhouse.command(f"INSERT INTO {target} SELECT * FROM {loading}")
                clickhouse.command(f"DROP TABLE IF EXISTS {loading}")
                total = int(clickhouse.command(f"SELECT count() FROM {target}"))
                return CopyOutcome(total - before, _cursor(clickhouse, target, cursor_column) or after, False)
            rows_loaded = int(clickhouse.command(f"SELECT count() FROM {loading}"))
            publish_raw_table(clickhouse, raw_table(source, spec))
            return CopyOutcome(rows_loaded, _cursor(clickhouse, target, cursor_column) if cursor_column else None, True)
        except BaseException:
            clickhouse.command(f"DROP TABLE IF EXISTS {loading}")
            raise
        finally:
            connection.close()
