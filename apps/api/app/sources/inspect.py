"""Test a source's connection and list its tables through ClickHouse (DECISIONS §4 Data sources).

The api has no PostgreSQL or MySQL driver. The catalog of the source system is read with the ``postgresql()``
and ``mysql()`` table functions through the source's named collection, which holds the credentials; the
database and schema are named in the call (``attach.scope_arguments``).

- PostgreSQL: ``pg_class`` and ``pg_stat_user_tables`` for the row estimate and the size (pages of 8 KiB),
  ``information_schema.columns`` for the columns and ``pg_constraint`` for the keys, because
  ``information_schema.table_constraints`` hides the constraints of a table the read-only user may only select.
- MySQL: ``information_schema`` ``TABLES``, ``COLUMNS`` and ``KEY_COLUMN_USAGE``.

Both estimates come from the source's statistics and can be stale, so the interface labels them approximate.
A failure is reported as one reason of ``REASONS`` and nothing the driver said: its text can name hosts and
users, and ClickHouse echoes parts of a statement.
"""

from dataclasses import dataclass, field
import re

from app.sources.attach import SourceLike, literal, scope_arguments

REASONS = ("unreachable", "refused", "authentication", "tls", "database_not_found", "permission", "unknown")
PAGE_BYTES = 8192
# Source column types ClickHouse cannot map one to one; it reads them as strings (or arrays) and the table list marks them.
POSTGRES_UNUSUAL = frozenset({"ARRAY", "USER-DEFINED", "json", "jsonb", "xml", "point", "line", "lseg", "box", "path",
                              "polygon", "circle", "tsvector", "tsquery", "hstore"})
MYSQL_UNUSUAL = frozenset({"json", "enum", "set", "geometry", "point", "linestring", "polygon", "multipoint",
                           "multilinestring", "multipolygon", "geometrycollection"})

# Checked in order: the first pattern that matches the driver's text names the reason.
_PATTERNS = (
    ("tls", re.compile(r"SSL|TLS|certificate verify", re.IGNORECASE)),
    ("database_not_found", re.compile(
        r'database "[^"]*" does not exist|ERROR 1049|Unknown database|ERROR 1044|to database', re.IGNORECASE)),
    ("authentication", re.compile(
        r"password authentication failed|ERROR 1045|authentication failed|no pg_hba\.conf entry", re.IGNORECASE)),
    ("permission", re.compile(
        r"permission denied|insufficient_privilege|ERROR 1142|ERROR 1143|command denied", re.IGNORECASE)),
    ("refused", re.compile(r"Connection refused|ERROR 2002|ERROR 2003|Can't connect to server", re.IGNORECASE)),
    ("unreachable", re.compile(
        r"could not translate host name|Name or service not known|Unknown server host|ERROR 2005|timeout expired|"
        r"Timeout exceeded|No route to host|Network is unreachable|ERROR 2013|ERROR 2006|timed out", re.IGNORECASE)),
)


class InspectError(RuntimeError):
    """The source could not be reached or read; ``reason`` is one of ``REASONS``."""

    def __init__(self, reason: str):
        super().__init__(f"the source could not be read: {reason}")
        self.reason = reason


def classify_error(error: BaseException) -> str:
    text = str(error)
    for reason, pattern in _PATTERNS:
        if pattern.search(text):
            return reason
    return "unknown"


@dataclass(frozen=True)
class CatalogColumn:
    name: str
    type: str
    nullable: bool
    position: int


@dataclass(frozen=True)
class ForeignKey:
    columns: tuple[str, ...]
    ref_table: str
    ref_columns: tuple[str, ...]


@dataclass(frozen=True)
class TableInfo:
    name: str
    kind: str
    rows: int | None
    size_bytes: int | None
    columns: tuple[CatalogColumn, ...] = ()
    primary_key: tuple[str, ...] = ()
    foreign_keys: tuple[ForeignKey, ...] = ()
    unusual_columns: tuple[str, ...] = field(default=())


def _int(value) -> int | None:
    return None if value is None else int(value)


class Inspector:
    def __init__(self, client):
        self._client = client

    def _rows(self, sql: str) -> list[tuple]:
        try:
            return [tuple(row) for row in self._client.query(sql).result_rows]
        except Exception as error:  # noqa: BLE001 - only the reason leaves this module
            raise InspectError(classify_error(error)) from None

    def check(self, source: SourceLike) -> None:
        """Connect and read the catalog once; raises ``InspectError`` with the reason it failed."""
        if source.kind == "postgres":
            self._rows(f"SELECT nspname FROM {self._pg(source, 'pg_catalog', 'pg_namespace')} LIMIT 1")
            return
        found = self._rows(
            f"SELECT SCHEMA_NAME FROM {self._my(source, 'SCHEMATA')} WHERE SCHEMA_NAME = {literal(source.database)}"
        )
        if not found:
            raise InspectError("database_not_found")

    @staticmethod
    def _pg(source: SourceLike, schema: str, table: str) -> str:
        return (f"postgresql({source.name}, database = {literal(source.database)}, "
                f"schema = {literal(schema)}, table = {literal(table)})")

    @staticmethod
    def _my(source: SourceLike, table: str) -> str:
        return f"mysql({source.name}, database = 'information_schema', table = {literal(table)})"

    def tables(self, source: SourceLike) -> list[TableInfo]:
        return self._postgres(source) if source.kind == "postgres" else self._mysql(source)

    def _postgres(self, source: SourceLike) -> list[TableInfo]:
        schema = literal(source.schema or "public")
        classes = self._rows(
            "SELECT c.relname, c.relkind, c.reltuples, c.relpages, c.oid "
            f"FROM {self._pg(source, 'pg_catalog', 'pg_class')} AS c "
            f"INNER JOIN {self._pg(source, 'pg_catalog', 'pg_namespace')} AS n ON c.relnamespace = n.oid "
            f"WHERE n.nspname = {schema} AND c.relkind IN ('r', 'p', 'v', 'm') ORDER BY c.relname"
        )
        live = dict(self._rows(
            "SELECT relname, n_live_tup "
            f"FROM {self._pg(source, 'pg_catalog', 'pg_stat_user_tables')} WHERE schemaname = {schema}"
        ))
        columns = self._rows(
            "SELECT table_name, column_name, data_type, udt_name, is_nullable, ordinal_position "
            f"FROM {self._pg(source, 'information_schema', 'columns')} WHERE table_schema = {schema} "
            "ORDER BY table_name, ordinal_position"
        )
        by_oid = {str(oid): name for name, _, _, _, oid in classes}
        constraints = self._rows(
            "SELECT conname, contype, conrelid, confrelid, conkey, confkey "
            f"FROM {self._pg(source, 'pg_catalog', 'pg_constraint')} WHERE contype IN ('p', 'f')"
        )
        constraints = [row for row in constraints if str(row[2]) in by_oid]
        attributes = {
            (str(relid), int(number)): name
            for relid, number, name in self._rows(
                "SELECT attrelid, attnum, attname "
                f"FROM {self._pg(source, 'pg_catalog', 'pg_attribute')} WHERE attnum > 0"
            )
        }

        def names(relid, numbers) -> tuple[str, ...]:
            return tuple(attributes[(str(relid), int(number))] for number in numbers if number is not None)

        primary: dict[str, tuple[str, ...]] = {}
        foreign: dict[str, list[ForeignKey]] = {}
        for _, kind, relid, confrelid, keys, ref_keys in constraints:
            table = by_oid[str(relid)]
            if kind == "p":
                primary[table] = names(relid, keys)
            elif str(confrelid) in by_oid:
                foreign.setdefault(table, []).append(
                    ForeignKey(names(relid, keys), by_oid[str(confrelid)], names(confrelid, ref_keys)))
        grouped = self._columns(columns, POSTGRES_UNUSUAL, type_index=2)
        result = []
        for name, relkind, reltuples, pages, _ in classes:
            is_view = relkind in ("v", "m")
            estimate = None if is_view else max(int(reltuples), int(live.get(name) or 0))
            cols, unusual = grouped.get(name, ((), ()))
            result.append(TableInfo(
                name=name, kind="view" if is_view else "table", rows=estimate,
                size_bytes=None if is_view else int(pages) * PAGE_BYTES, columns=cols,
                primary_key=primary.get(name, ()), foreign_keys=tuple(foreign.get(name, ())), unusual_columns=unusual))
        return result

    @staticmethod
    def _columns(rows: list[tuple], unusual_types: frozenset[str], type_index: int):
        grouped: dict[str, tuple[list[CatalogColumn], list[str]]] = {}
        for row in rows:
            table, name, kind, nullable, position = row[0], row[1], row[type_index], row[4], row[5]
            columns, unusual = grouped.setdefault(table, ([], []))
            columns.append(CatalogColumn(name, str(kind), str(nullable).upper() == "YES", int(position)))
            if kind in unusual_types:
                unusual.append(name)
        return {table: (tuple(columns), tuple(unusual)) for table, (columns, unusual) in grouped.items()}

    def _mysql(self, source: SourceLike) -> list[TableInfo]:
        schema = literal(source.database)
        tables = self._rows(
            "SELECT TABLE_NAME, TABLE_TYPE, TABLE_ROWS, DATA_LENGTH, INDEX_LENGTH "
            f"FROM {self._my(source, 'TABLES')} WHERE TABLE_SCHEMA = {schema} ORDER BY TABLE_NAME"
        )
        columns = self._rows(
            "SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, COLUMN_TYPE, IS_NULLABLE, ORDINAL_POSITION "
            f"FROM {self._my(source, 'COLUMNS')} WHERE TABLE_SCHEMA = {schema} ORDER BY TABLE_NAME, ORDINAL_POSITION"
        )
        keys = self._rows(
            "SELECT CONSTRAINT_NAME, TABLE_NAME, COLUMN_NAME, ORDINAL_POSITION, REFERENCED_TABLE_NAME, "
            f"REFERENCED_COLUMN_NAME FROM {self._my(source, 'KEY_COLUMN_USAGE')} WHERE TABLE_SCHEMA = {schema} "
            "ORDER BY TABLE_NAME, CONSTRAINT_NAME, ORDINAL_POSITION"
        )
        primary: dict[str, list[str]] = {}
        foreign: dict[tuple[str, str], tuple[list[str], str, list[str]]] = {}
        for constraint, table, column, _, ref_table, ref_column in keys:
            if constraint == "PRIMARY":
                primary.setdefault(table, []).append(column)
            elif ref_table:
                entry = foreign.setdefault((table, constraint), ([], ref_table, []))
                entry[0].append(column)
                entry[2].append(ref_column)
        grouped = self._columns(columns, MYSQL_UNUSUAL, type_index=2)
        result = []
        for name, table_type, rows, data_length, index_length in tables:
            is_view = table_type == "VIEW"
            cols, unusual = grouped.get(name, ((), ()))
            size = None if is_view or data_length is None else int(data_length) + int(index_length or 0)
            result.append(TableInfo(
                name=name, kind="view" if is_view else "table", rows=None if is_view else _int(rows), size_bytes=size,
                columns=cols, primary_key=tuple(primary.get(name, ())),
                foreign_keys=tuple(ForeignKey(tuple(c), ref, tuple(rc))
                                   for (table, _), (c, ref, rc) in foreign.items() if table == name),
                unusual_columns=unusual))
        return result
