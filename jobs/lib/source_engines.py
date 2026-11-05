"""ClickHouse SQL that reaches a source manifest's tables (DECISIONS §4 Data sources).

Every source is read through the ClickHouse named collection named after it,
so no statement here holds a host or a credential:

- copy mode reads each table with a table function (``postgresql``, ``mysql``,
  ``mongodb`` or ``s3``) into ``raw.<source>__<table>``;
- live mode attaches database ``src_<source>``: a ``PostgreSQL`` or ``MySQL``
  database engine, or one ``MongoDB`` or ``S3`` table engine per table.

``relations`` tells dbt where each table is in the chosen mode. Names come
from a validated manifest; identifiers are still quoted and literals escaped.
"""

from jobs.lib.source_manifest import HUGGINGFACE, SourceManifest, TableSpec

RAW_DATABASE = "raw"
LIVE_PREFIX = "src_"
DATABASE_ENGINES = {"postgres": "PostgreSQL", "mysql": "MySQL"}
TABLE_FUNCTIONS = {"postgres": "postgresql", "mysql": "mysql"}
FILE_FORMATS = {"csv": "CSVWithNames", "parquet": "Parquet"}


def quote(identifier: str) -> str:
    return "`" + identifier.replace("\\", "\\\\").replace("`", "\\`") + "`"


def literal(text: str) -> str:
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


def raw_table(manifest: SourceManifest, table: TableSpec) -> str:
    return f"{manifest.name}__{table.name}"


def live_database(manifest: SourceManifest) -> str:
    return LIVE_PREFIX + manifest.name


def _structure(table: TableSpec) -> str:
    return ", ".join(f"{quote(column.name)} {column.type}" for column in table.columns)


def table_function(manifest: SourceManifest, table: TableSpec) -> str:
    """The table function that reads ``table`` for a copy."""
    collection = manifest.name
    if manifest.kind in TABLE_FUNCTIONS:
        return f"{TABLE_FUNCTIONS[manifest.kind]}({collection}, table = {literal(table.source_name)})"
    if manifest.kind == "mongodb":
        return (
            f"mongodb({collection}, collection = {literal(table.source_name)}, "
            f"structure = {literal(_structure(table))})"
        )
    if manifest.kind == "files":
        arguments = f"filename = {literal(table.source_name)}, format = {literal(FILE_FORMATS[table.format])}"
        if table.columns:
            arguments += f", structure = {literal(_structure(table))}"
        return f"s3({collection}, {arguments})"
    raise ValueError(f"a {manifest.kind} source is loaded by jobs.load_data, not through a table function")


def live_statements(manifest: SourceManifest) -> list[str]:
    """DDL that defines ``src_<source>``; running it again replaces the table engines in place."""
    if manifest.kind == HUGGINGFACE:
        raise ValueError(f"{manifest.name}: a {HUGGINGFACE} source cannot be read live")
    database = quote(live_database(manifest))
    collection = manifest.name
    if manifest.kind in DATABASE_ENGINES:
        return [f"CREATE DATABASE IF NOT EXISTS {database} ENGINE = {DATABASE_ENGINES[manifest.kind]}({collection})"]
    statements = [f"CREATE DATABASE IF NOT EXISTS {database}"]
    for table in manifest.tables:
        columns = f" ({_structure(table)})" if table.columns else ""
        if manifest.kind == "mongodb":
            engine = f"MongoDB({collection}, collection = {literal(table.source_name)})"
        else:
            engine = (
                f"S3({collection}, filename = {literal(table.source_name)}, "
                f"format = {literal(FILE_FORMATS[table.format])})"
            )
        statements.append(f"CREATE OR REPLACE TABLE {database}.{quote(table.name)}{columns} ENGINE = {engine}")
    return statements


def relations(manifest: SourceManifest) -> dict[str, str]:
    """``{table: relation}`` that the dbt staging models read in the manifest's mode."""
    if manifest.mode != "live":
        return {table.name: f"{quote(RAW_DATABASE)}.{quote(raw_table(manifest, table))}" for table in manifest.tables}
    database = quote(live_database(manifest))
    # A database engine lists each table under its name in the source system.
    by_source = manifest.kind in DATABASE_ENGINES
    return {
        table.name: f"{database}.{quote(table.source_name if by_source else table.name)}" for table in manifest.tables
    }
