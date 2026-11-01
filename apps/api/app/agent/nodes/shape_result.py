"""Type the returned rows into a Result (DECISIONS §6 step 14).

A column named like a dataset column takes that column's type and role; one
named like a metric, or starting with a metric id and "_" (for example a
metric per period), is a measure in the metric's unit; a name with a "pct"
or "percent" part is a percentage. Other columns are typed from their
ClickHouse type. Values become JSON-friendly and rows are capped at 5,000,
with ``truncated`` set when the query returned more.
"""

from datetime import date, datetime
from decimal import Decimal
import re

from app.agent.state import AgentDeps, AgentState
from app.contracts.result import MAX_RESULT_ROWS, ColumnInfo, Result
from app.data.clickhouse import QueryOutput
from app.packs.models import Pack

_WRAPPER = re.compile(r"^(?:Nullable|LowCardinality)\((.*)\)$")


def _base_type(clickhouse_type: str) -> str:
    while match := _WRAPPER.match(clickhouse_type):
        clickhouse_type = match.group(1)
    return clickhouse_type


def value_type(clickhouse_type: str) -> str:
    base = _base_type(clickhouse_type)
    if re.match(r"^(U?Int\d+|Float\d+|Decimal)", base):
        return "number"
    if base.startswith("DateTime"):
        return "datetime"
    if base.startswith("Date"):
        return "date"
    if base == "Bool":
        return "boolean"
    return "string"


def _is_percent(name: str) -> bool:
    return bool({"pct", "percent"} & set(name.lower().split("_")))


def describe_column(name: str, clickhouse_type: str, pack: Pack, dataset: str) -> ColumnInfo:
    kind = value_type(clickhouse_type)
    if _is_percent(name):
        return ColumnInfo(name=name, type=kind, role="measure", format="percent")
    for metric in pack.metrics.metrics:
        if name == metric.id or name.startswith(f"{metric.id}_"):
            return ColumnInfo(name=name, type=kind, role="measure", format=metric.unit)
    columns = {column.name: column for item in pack.datasets.datasets if item.id == dataset for column in item.columns}
    if name in columns:
        column = columns[name]
        return ColumnInfo(name=name, type=column.type if column.type == kind or kind == "string" else kind, role=column.role)
    role = "measure" if kind == "number" else "time" if kind in ("date", "datetime") else "dimension"
    return ColumnInfo(name=name, type=kind, role=role)


def _cell(value: object) -> object:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def to_result(output: QueryOutput, pack: Pack, dataset: str) -> Result:
    columns = [describe_column(name, kind, pack, dataset) for name, kind in zip(output.columns, output.types, strict=True)]
    rows = [[_cell(value) for value in row] for row in output.rows[:MAX_RESULT_ROWS]]
    return Result(columns=columns, rows=rows, row_count=len(output.rows), truncated=len(output.rows) > MAX_RESULT_ROWS)


def shape_result(state: AgentState, deps: AgentDeps) -> dict:
    result = to_result(state["output"], deps.compiled.pack, state["spec"].dataset)
    warnings = list(state.get("warnings", []))
    if result.truncated:
        warnings.append(f"only the first {MAX_RESULT_ROWS} rows are shown")
    return {"result": result, "warnings": warnings}
