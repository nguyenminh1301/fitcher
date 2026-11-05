"""Deterministic profile of the marts a pack reads (DECISIONS §11 step 2); no LLM is called.

``profile_marts`` reads ``system.columns`` and a few bounded queries per
table and returns the dictionary ``jobs.profile`` writes to
``build/packs/<pack>/profile.json``:

.. code-block:: text

    {
      "profiled_at": ISO 8601 time,
      "tables": {
        <table>: {
          "rows": int,
          "columns": {
            <column>: {
              "type": "string" | "number" | "date" | "datetime" | "boolean" | "other",
              "distinct": int,                       # exact distinct values
              "min": str, "max": str,                # date and datetime columns of a non-empty table
              "top_values": [[value, count], ...]    # string columns with at most low_cardinality values
            }
          },
          "sample_rows": [[value, ...], ...]         # the first sample_rows rows, in column order
        }
      },
      "join_candidates": [{"left": "t.c", "right": "t.c", "overlap": 0..1}]
    }

A join candidate is a column name shared by two profiled tables with
compatible types; ``overlap`` is the share of the left column's distinct
values found in the right column. The drafter cites a profile fact as
evidence ``{kind: profile, ref: "<table>"}`` or ``"<table>.<column>"``.
"""

from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from itertools import combinations
from pathlib import Path
import re

from app.packs.compiler import MARTS_DATABASE, SCAN_SETTINGS, CompileError, Warehouse, quote, table_ref

_WRAPPER = re.compile(r"^(Nullable|LowCardinality)\((.*)\)$")


def profile_path(output_dir: Path, pack: str) -> Path:
    return output_dir / pack / "profile.json"


def base_type(clickhouse_type: str) -> str:
    """The pack column type of a ClickHouse type, or ``other`` for arrays, maps and the like."""
    name = clickhouse_type.strip()
    while match := _WRAPPER.match(name):
        name = match.group(2).strip()
    if name in ("String", "UUID") or name.startswith(("FixedString", "Enum")):
        return "string"
    if name.startswith("DateTime"):
        return "datetime"
    if name.startswith("Date"):
        return "date"
    if name == "Bool":
        return "boolean"
    if re.match(r"(U?Int\d+|Float\d+|Decimal)", name):
        return "number"
    return "other"


def _json_value(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def _scalar(warehouse: Warehouse, sql: str) -> object:
    return warehouse.query(sql, settings=SCAN_SETTINGS)[0][0]


def _columns(warehouse: Warehouse, tables: Sequence[str]) -> dict[str, list[tuple[str, str]]]:
    names = ", ".join(f"'{table}'" for table in tables)
    rows = warehouse.query(
        f"SELECT table, name, type FROM system.columns WHERE database = '{MARTS_DATABASE}' AND table IN ({names}) "
        "ORDER BY table, position",
        settings=SCAN_SETTINGS,
    )
    found: dict[str, list[tuple[str, str]]] = {}
    for table, column, column_type in rows:
        found.setdefault(table, []).append((column, column_type))
    return found


def _profile_column(warehouse: Warehouse, table: str, column: str, kind: str, rows: int, top_k: int, low_cardinality: int) -> dict:
    facts: dict = {"type": kind, "distinct": 0}
    if not rows:
        return facts
    name = quote(column)
    facts["distinct"] = int(_scalar(warehouse, f"SELECT uniqExact({name}) FROM {table_ref(table)}"))
    if kind in ("date", "datetime"):
        low, high = warehouse.query(f"SELECT min({name}), max({name}) FROM {table_ref(table)}", settings=SCAN_SETTINGS)[0]
        facts["min"], facts["max"] = _json_value(low), _json_value(high)
    if kind == "string" and facts["distinct"] <= low_cardinality:
        values = warehouse.query(
            f"SELECT toString({name}) AS value, count() AS n FROM {table_ref(table)} "
            f"GROUP BY value ORDER BY n DESC, value LIMIT {int(top_k)}",
            settings=SCAN_SETTINGS,
        )
        facts["top_values"] = [[value, int(count)] for value, count in values]
    return facts


def _join_candidates(warehouse: Warehouse, profiled: dict[str, dict]) -> list[dict]:
    candidates: list[dict] = []
    for left, right in combinations(sorted(profiled), 2):
        if not profiled[left]["rows"] or not profiled[right]["rows"]:
            continue
        for column, facts in profiled[left]["columns"].items():
            other = profiled[right]["columns"].get(column)
            if other is None or facts["type"] != other["type"] or facts["type"] not in ("string", "number"):
                continue
            name = quote(column)
            overlap = _scalar(
                warehouse,
                f"SELECT uniqExactIf({name}, {name} IN (SELECT {name} FROM {table_ref(right)})) "
                f"/ nullIf(uniqExact({name}), 0) FROM {table_ref(left)}",
            )
            candidates.append({
                "left": f"{left}.{column}", "right": f"{right}.{column}",
                "overlap": round(float(overlap or 0.0), 4),
            })
    return candidates


def profile_marts(
    warehouse: Warehouse,
    tables: Sequence[str],
    *,
    top_k: int = 20,
    low_cardinality: int = 50,
    sample_rows: int = 3,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict:
    """Profile ``tables`` in ``marts``; raise CompileError for an unsafe or missing table."""
    for table in tables:
        quote(table)
    found = _columns(warehouse, tables)
    for table in tables:
        if table not in found:
            raise CompileError(f"marts has no table '{table}'")
    profiled: dict[str, dict] = {}
    for table in tables:
        rows = int(_scalar(warehouse, f"SELECT count() FROM {table_ref(table)}"))
        columns = {
            column: _profile_column(warehouse, table, column, base_type(column_type), rows, top_k, low_cardinality)
            for column, column_type in found[table]
        }
        samples = warehouse.query(
            f"SELECT * FROM {table_ref(table)} LIMIT {int(sample_rows)}", settings=SCAN_SETTINGS
        ) if rows else []
        profiled[table] = {
            "rows": rows, "columns": columns, "sample_rows": [[_json_value(value) for value in row] for row in samples],
        }
    return {"profiled_at": clock().isoformat(), "tables": profiled, "join_candidates": _join_candidates(warehouse, profiled)}
