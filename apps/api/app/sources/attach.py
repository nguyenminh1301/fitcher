"""ClickHouse SQL that reaches, copies and attaches a source's tables (DECISIONS §4 Data sources).

Both the source manifests of ``jobs`` and the sources of the Sources page are
read through the ClickHouse named collection named after the source, so no
statement here holds a host or a credential:

- copy mode reads each table with a table function (``postgresql``, ``mysql``,
  ``mongodb`` or ``s3``) into ``raw.<source>__<table>``;
- live mode attaches database ``src_<source>``: a ``PostgreSQL`` or ``MySQL``
  database engine, or one ``MongoDB`` or ``S3`` table engine per table.

A source and its tables are any objects with the attributes of ``Source`` and
``Table``: the manifest dataclasses of ``jobs`` fit as they are. Names come
from a validated manifest or from ``valid_name``; identifiers are still quoted
and literals escaped.
"""

from dataclasses import dataclass
import re
from typing import Protocol

RAW_DATABASE = "raw"
LIVE_PREFIX = "src_"
LOADING_SUFFIX = "__loading"
HUGGINGFACE = "huggingface"
DATABASE_ENGINES = {"postgres": "PostgreSQL", "mysql": "MySQL"}
TABLE_FUNCTIONS = {"postgres": "postgresql", "mysql": "mysql"}
FILE_FORMATS = {"csv": "CSVWithNames", "parquet": "Parquet"}
NAME = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
# Databases of the application that a source must not be named after.
RESERVED_NAMES = frozenset({"raw", "marts", "agent_logs", "data_meta", "system", "default", "information_schema"})


@dataclass(frozen=True)
class Column:
    name: str
    type: str


@dataclass(frozen=True)
class Table:
    """A table of a source: its name here, its name there (``source_name``) and, for a file, its format."""

    name: str
    source_name_override: str | None = None
    columns: tuple[Column, ...] = ()
    format: str | None = None

    def __init__(self, name: str, source_name: str | None = None, columns: tuple[Column, ...] = (),
                 format: str | None = None):
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "source_name_override", source_name)
        object.__setattr__(self, "columns", columns)
        object.__setattr__(self, "format", format)

    @property
    def source_name(self) -> str:
        return self.source_name_override or self.name


@dataclass(frozen=True)
class Source:
    name: str
    kind: str
    tables: tuple[Table, ...] = ()
    mode: str = "copy"


class TableLike(Protocol):
    name: str
    source_name: str
    columns: tuple
    format: str | None


class SourceLike(Protocol):
    name: str
    kind: str
    mode: str
    tables: tuple


@dataclass(frozen=True)
class CopyOutcome:
    """What one copy of a table did: rows loaded, whether it replaced the copy, and the new cursor value."""

    rows: int
    cursor: str | None
    full: bool


def valid_name(name: str) -> bool:
    return bool(NAME.match(name)) and name not in RESERVED_NAMES


def quote(identifier: str) -> str:
    return "`" + identifier.replace("\\", "\\\\").replace("`", "\\`") + "`"


def literal(text: str) -> str:
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


def raw_table(source: SourceLike, table: TableLike) -> str:
    return f"{source.name}__{table.name}"


def live_database(source: SourceLike) -> str:
    return LIVE_PREFIX + source.name


def raw_relation(source: SourceLike, table: TableLike) -> str:
    return f"{quote(RAW_DATABASE)}.{quote(raw_table(source, table))}"


def loading_table(name: str) -> str:
    return f"{quote(RAW_DATABASE)}.{quote(name + LOADING_SUFFIX)}"


def _structure(table: TableLike) -> str:
    return ", ".join(f"{quote(column.name)} {column.type}" for column in table.columns)


def table_function(source: SourceLike, table: TableLike) -> str:
    """The table function that reads ``table`` for a copy."""
    collection = source.name
    if source.kind in TABLE_FUNCTIONS:
        return f"{TABLE_FUNCTIONS[source.kind]}({collection}, table = {literal(table.source_name)})"
    if source.kind == "mongodb":
        return (
            f"mongodb({collection}, collection = {literal(table.source_name)}, "
            f"structure = {literal(_structure(table))})"
        )
    if source.kind == "files":
        arguments = f"filename = {literal(table.source_name)}, format = {literal(FILE_FORMATS[table.format])}"
        if table.columns:
            arguments += f", structure = {literal(_structure(table))}"
        return f"s3({collection}, {arguments})"
    raise ValueError(f"a {source.kind} source is loaded by jobs.load_data, not through a table function")


def live_statements(source: SourceLike) -> list[str]:
    """DDL that defines ``src_<source>``; running it again replaces the table engines in place."""
    if source.kind == HUGGINGFACE:
        raise ValueError(f"{source.name}: a {HUGGINGFACE} source cannot be read live")
    database = quote(live_database(source))
    collection = source.name
    if source.kind in DATABASE_ENGINES:
        return [f"CREATE DATABASE IF NOT EXISTS {database} ENGINE = {DATABASE_ENGINES[source.kind]}({collection})"]
    statements = [f"CREATE DATABASE IF NOT EXISTS {database}"]
    for table in source.tables:
        columns = f" ({_structure(table)})" if table.columns else ""
        if source.kind == "mongodb":
            engine = f"MongoDB({collection}, collection = {literal(table.source_name)})"
        else:
            engine = (
                f"S3({collection}, filename = {literal(table.source_name)}, "
                f"format = {literal(FILE_FORMATS[table.format])})"
            )
        statements.append(f"CREATE OR REPLACE TABLE {database}.{quote(table.name)}{columns} ENGINE = {engine}")
    return statements


def relations(source: SourceLike) -> dict[str, str]:
    """``{table: relation}`` that the dbt staging models read in the source's mode."""
    if source.mode != "live":
        return {table.name: raw_relation(source, table) for table in source.tables}
    database = quote(live_database(source))
    # A database engine lists each table under its name in the source system.
    by_source = source.kind in DATABASE_ENGINES
    return {
        table.name: f"{database}.{quote(table.source_name if by_source else table.name)}" for table in source.tables
    }


def _drop_loading(client, source: SourceLike, table: TableLike) -> None:
    client.command(f"DROP TABLE IF EXISTS {loading_table(raw_table(source, table))}")


def stage_copy(client, source: SourceLike, table: TableLike) -> int:
    """Read ``table`` into its loading table and return its row count; a failure drops the loading table."""
    loading = loading_table(raw_table(source, table))
    _drop_loading(client, source, table)
    try:
        client.command(
            f"CREATE TABLE {loading} ENGINE = MergeTree ORDER BY tuple() "
            f"AS SELECT * FROM {table_function(source, table)}"
        )
        return int(client.command(f"SELECT count() FROM {loading}"))
    except Exception:
        _drop_loading(client, source, table)
        raise


def publish_raw_table(client, name: str) -> None:
    """Make the loading table of ``name`` the published copy: a rename the first time, an exchange after."""
    loading, target = loading_table(name), f"{quote(RAW_DATABASE)}.{quote(name)}"
    if int(client.command(f"EXISTS TABLE {target}")):
        client.command(f"EXCHANGE TABLES {loading} AND {target}")
        client.command(f"DROP TABLE {loading}")
    else:
        client.command(f"RENAME TABLE {loading} TO {target}")


def publish_copy(client, source: SourceLike, table: TableLike) -> None:
    publish_raw_table(client, raw_table(source, table))


def _cursor(client, relation: str, column: str) -> str | None:
    value = client.command(f"SELECT toString(max({quote(column)})) FROM {relation}")
    return None if value in (None, "", 0) else str(value)


def copy_table(client, source: SourceLike, table: TableLike, *, cursor_column: str | None,
               after: str | None) -> CopyOutcome:
    """Copy one table into ``raw``.

    Without a cursor column, or without a value seen yet, the table is reloaded and swapped in atomically.
    With both, only the rows whose cursor column is above ``after`` are read; they are staged first and
    appended in one local insert, so a failed read leaves the copy as it was.
    """
    if cursor_column is None or after is None or not int(client.command(f"EXISTS TABLE {raw_relation(source, table)}")):
        rows = stage_copy(client, source, table)
        publish_copy(client, source, table)
        return CopyOutcome(rows, _cursor(client, raw_relation(source, table), cursor_column) if cursor_column else None, True)
    target, loading = raw_relation(source, table), loading_table(raw_table(source, table))
    before = int(client.command(f"SELECT count() FROM {target}"))
    _drop_loading(client, source, table)
    try:
        client.command(f"CREATE TABLE {loading} AS {target}")
        client.command(
            f"INSERT INTO {loading} SELECT * FROM {table_function(source, table)} "
            f"WHERE {quote(cursor_column)} > {literal(after)}"
        )
        client.command(f"INSERT INTO {target} SELECT * FROM {loading}")
    finally:
        _drop_loading(client, source, table)
    total = int(client.command(f"SELECT count() FROM {target}"))
    return CopyOutcome(total - before, _cursor(client, target, cursor_column) or after, False)


def attach_live(client, source: SourceLike) -> dict[str, int]:
    """Define ``src_<source>`` and count each table through it, which proves the source answers."""
    for statement in live_statements(source):
        client.command(statement)
    return {
        table.name: int(client.command(f"SELECT count() FROM {relation}"))
        for table, relation in zip(source.tables, relations(_as_live(source)).values(), strict=True)
    }


def _as_live(source: SourceLike) -> Source:
    return Source(source.name, source.kind, tuple(source.tables), mode="live")


def drop_source(client, source: SourceLike) -> None:
    """Drop the live database and every copy of a source."""
    client.command(f"DROP DATABASE IF EXISTS {quote(live_database(source))}")
    for table in source.tables:
        client.command(f"DROP TABLE IF EXISTS {raw_relation(source, table)}")
        _drop_loading(client, source, table)
