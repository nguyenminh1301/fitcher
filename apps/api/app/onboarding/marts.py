"""Mart views over the selected tables of a source, for an instant pack (DECISIONS §4, §11 step 0).

Each selected table becomes ``marts.<source>__<table>``, a view with ``SQL SECURITY DEFINER`` over the table's
relation (``src_<source>`` when read live, ``raw`` when copied), so an agent role granted the mart reads the
source through it without any grant on ``src_*`` or ``raw``. Columns keep their names; nothing is renamed by an
LLM. Only what the pack cannot describe changes, deterministically:

- a name that is not an identifier has every other character replaced with ``_`` (mart names are also lower-cased,
  because a dataset id is);
- a column of a type the pack has no column type for (arrays, maps, network addresses...) is cast to a string;
- a string column whose sampled non-empty values all parse as a date, a date and time or a number is cast to that
  type (``text_kinds_query``): many sources keep dates and amounts as text, and a dataset needs a time column.

A table with a single-column foreign key to another selected table also gets ``marts.<source>__<table>__wide``,
because the agent works best on wide marts with few joins: it joins every such referenced table one level deep and
names each joined column ``<referenced table>_<column>`` (the key column of a table referenced twice is used as
the prefix the second time), leaving the referenced key out because the table's own key column holds it. A wide
view that reads a live table is ``slow``: ClickHouse reads the live rows and joins them itself.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
import re

from app.onboarding.profiler import base_type
from app.sources.attach import Source, Table, literal, quote, relations
from app.sources.inspect import ForeignKey

MARTS_DATABASE = "marts"
WIDE_SUFFIX = "__wide"
TEXT_SAMPLE_ROWS = 100_000
# Cast of a string column whose sampled values all parse as the kind.
TEXT_CASTS = {"date": "toDateOrNull", "datetime": "parseDateTime64BestEffortOrNull", "number": "toFloat64OrNull"}
# Patterns a non-empty value must match to count as the kind; a number with a leading zero is a code, not a number.
TEXT_PATTERNS = {
    "date": r"^\d{4}-\d{2}-\d{2}$",
    "datetime": r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$",
    "number": r"^-?(0|[1-9]\d*)(\.\d+)?$",
}
_NOT_IDENTIFIER = re.compile(r"[^A-Za-z0-9_]")


@dataclass(frozen=True)
class SourceColumn:
    name: str
    # The column's type as ClickHouse reads it from the relation.
    type: str


@dataclass(frozen=True)
class MartTable:
    """A selected table: its name at the source, the relation ClickHouse reads it from and its catalog."""

    name: str
    relation: str
    live: bool
    columns: tuple[SourceColumn, ...]
    primary_key: tuple[str, ...] = ()
    foreign_keys: tuple[ForeignKey, ...] = ()
    # Kinds found by ``text_kinds_query`` for string columns: date, datetime or number.
    text_kinds: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class MartView:
    name: str
    # The source table the view is built for.
    table: str
    sql: str
    columns: tuple[str, ...]
    wide: bool = False
    slow: bool = False
    # (key column, referenced table) of each join of a wide view.
    joins: tuple[tuple[str, str], ...] = ()

    def statement(self) -> str:
        return (f"CREATE OR REPLACE VIEW {quote(MARTS_DATABASE)}.{quote(self.name)} "
                f"DEFINER = CURRENT_USER SQL SECURITY DEFINER AS {self.sql}")


def _safe(name: str) -> str:
    safe = _NOT_IDENTIFIER.sub("_", name)
    return safe if safe and not safe[0].isdigit() else f"_{safe}"


def safe_column(name: str) -> str:
    return _safe(name)


def mart_name(source: str, table: str) -> str:
    return f"{source}__{_safe(table).lower()}"


def wide_name(source: str, table: str) -> str:
    return mart_name(source, table) + WIDE_SUFFIX


def _expression(column: SourceColumn, kinds: dict[str, str], alias: str | None) -> str:
    reference = f"{alias}.{quote(column.name)}" if alias else quote(column.name)
    if column.name in kinds:
        return f"{TEXT_CASTS[kinds[column.name]]}({reference})"
    if base_type(column.type) == "other":
        return f"toString({reference})"
    return reference


def _output_names(table: MartTable) -> list[str]:
    names: list[str] = []
    for column in table.columns:
        name, number = _safe(column.name), 2
        while name in names:
            name, number = f"{_safe(column.name)}_{number}", number + 1
        names.append(name)
    return names


def _select(table: MartTable, alias: str | None) -> list[tuple[str, str]]:
    """(output name, expression) of each column of ``table``."""
    return [(name, _expression(column, table.text_kinds, alias))
            for column, name in zip(table.columns, _output_names(table), strict=True)]


def _render(items: list[tuple[str, str]], qualified: bool) -> str:
    rendered = []
    for name, expression in items:
        rendered.append(expression if not qualified and expression == quote(name) else f"{expression} AS {quote(name)}")
    return ", ".join(rendered)


def _base_view(source: str, table: MartTable) -> MartView:
    items = _select(table, None)
    return MartView(name=mart_name(source, table.name), table=table.name,
                    sql=f"SELECT {_render(items, False)} FROM {table.relation}", columns=tuple(name for name, _ in items))


def _joins(table: MartTable, selected: dict[str, MartTable]) -> list[tuple[ForeignKey, MartTable]]:
    return [(key, selected[key.ref_table]) for key in table.foreign_keys
            if len(key.columns) == 1 and key.ref_table in selected and key.ref_table != table.name]


def _wide_view(source: str, table: MartTable, joins: list[tuple[ForeignKey, MartTable]]) -> MartView:
    items = _select(table, "f")
    names = {name for name, _ in items}
    clauses, used = [], set()
    for number, (key, dimension) in enumerate(joins, start=1):
        alias = f"d{number}"
        prefix = _safe(dimension.name).lower() if dimension.name not in used else _safe(key.columns[0])
        used.add(dimension.name)
        for (name, expression), column in zip(_select(dimension, alias), dimension.columns, strict=True):
            if column.name == key.ref_columns[0]:
                continue
            output = f"{prefix}_{name}"
            if output not in names:
                names.add(output)
                items.append((output, expression))
        clauses.append(f"LEFT JOIN {dimension.relation} AS {alias} "
                       f"ON f.{quote(key.columns[0])} = {alias}.{quote(key.ref_columns[0])}")
    sql = (f"SELECT {_render(items, True)} FROM {table.relation} AS f {' '.join(clauses)} "
           "SETTINGS join_use_nulls = 1")
    return MartView(
        name=wide_name(source, table.name), table=table.name, sql=sql, columns=tuple(name for name, _ in items),
        wide=True, slow=table.live or any(dimension.live for _, dimension in joins),
        joins=tuple((key.columns[0], dimension.name) for key, dimension in joins),
    )


def plan_marts(source: str, tables: Sequence[MartTable]) -> list[MartView]:
    """The views of ``tables``: each table's own view, then the wide views, in the order of ``tables``."""
    selected = {table.name: table for table in tables}
    views = [_base_view(source, table) for table in tables]
    for table in tables:
        joins = _joins(table, selected)
        if joins:
            views.append(_wide_view(source, table, joins))
    return views


def text_kinds_query(relation: str, columns: Sequence[SourceColumn], sample_rows: int = TEXT_SAMPLE_ROWS) -> str | None:
    """One query over a bounded sample that counts, per string column, its non-empty values and those of each kind.

    Its single row holds, for each string column in order, the counts ``non-empty, date, datetime, number``;
    ``text_kinds`` turns it into the kinds. None when the table has no string column.
    """
    strings = [column.name for column in columns if base_type(column.type) == "string" and "String" in column.type]
    if not strings:
        return None
    counts = []
    for name in strings:
        value = quote(name)
        present = f"({value} IS NOT NULL AND {value} != '')"
        counts.append(f"countIf({present})")
        for kind, pattern in TEXT_PATTERNS.items():
            escaped = pattern.replace("\\", "\\\\")
            counts.append(f"countIf({present} AND match({value}, '{escaped}') AND {TEXT_CASTS[kind]}({value}) IS NOT NULL)")
    columns_sql = ", ".join(quote(name) for name in strings)
    return f"SELECT {', '.join(counts)} FROM (SELECT {columns_sql} FROM {relation} LIMIT {int(sample_rows)})"


def text_kinds(columns: Sequence[SourceColumn], row: Sequence[int]) -> dict[str, str]:
    """The kind of each string column whose sampled non-empty values all parse; read from ``text_kinds_query``."""
    strings = [column.name for column in columns if base_type(column.type) == "string" and "String" in column.type]
    kinds: dict[str, str] = {}
    width = 1 + len(TEXT_PATTERNS)
    for index, name in enumerate(strings):
        present, *matches = (int(value) for value in row[index * width:(index + 1) * width])
        for kind, matched in zip(TEXT_PATTERNS, matches, strict=True):
            if present and matched == present:
                kinds[name] = kind
                break
    return kinds


def mart_tables(client, source_id: str, kind: str, tables: Sequence) -> list[MartTable]:
    """Describe each selected table (``StoredTable``) where ClickHouse reads it and sample its string columns."""
    found = []
    for table in tables:
        live = table.mode == "live"
        relation = relations(Source(source_id, kind, (Table(table.name),), mode="live" if live else "copy"))[table.name]
        columns = tuple(SourceColumn(str(row[0]), str(row[1])) for row in client.query(f"DESCRIBE TABLE {relation}").result_rows)
        sample = text_kinds_query(relation, columns)
        kinds = text_kinds(columns, client.query(sample).result_rows[0]) if sample else {}
        found.append(MartTable(name=table.name, relation=relation, live=live, columns=columns,
                               primary_key=tuple(table.primary_key), foreign_keys=tuple(table.foreign_keys), text_kinds=kinds))
    return found


def source_marts(client, source_id: str) -> list[str]:
    """The views of ``marts`` named after the source: the marts an instant pack built for it."""
    rows = client.query(
        f"SELECT name FROM system.tables WHERE database = {literal(MARTS_DATABASE)} AND engine = 'View' "
        f"AND startsWith(name, {literal(source_id + '__')}) ORDER BY name").result_rows
    return [str(row[0]) for row in rows]


def apply_marts(client, source_id: str, views: Sequence[MartView]) -> list[str]:
    """Create or replace ``views``, then drop the source's other marts; returns the names dropped."""
    existing = source_marts(client, source_id)
    for view in views:
        client.command(view.statement())
    planned = {view.name for view in views}
    dropped = [name for name in existing if name not in planned]
    for name in dropped:
        client.command(f"DROP VIEW IF EXISTS {quote(MARTS_DATABASE)}.{quote(name)}")
    return dropped
