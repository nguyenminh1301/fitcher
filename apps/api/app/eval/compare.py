"""Compare an answer's result set with the reference result (DECISIONS §12).

Result sets are compared, never SQL strings, and columns are matched by
value rather than by name or position: each reference key column (dimension
or time) and each reference measure must match a distinct answer column of
the same kind, so renamed or reordered columns still match and extra answer
columns, such as a percentage change, are allowed. Rows are aligned by their
key values; their order matters only when the case ranks. Numbers match
within ``|a - b| <= max(rel * max(|a|, |b|), abs)``, so zero-valued measures
compare safely.
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from app.contracts.result import Cell, Result

Value = str | float | bool | None


@dataclass(frozen=True)
class Tolerance:
    rel: float = 1e-6
    abs: float = 1e-9


@dataclass(frozen=True)
class Comparison:
    match: bool
    reason: str | None = None


def _normalize(value: object) -> Value:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _order(value: Value) -> tuple:
    """Sort key that orders values of mixed types without comparing across types."""
    if value is None:
        return (0, "")
    if isinstance(value, bool):
        return (1, int(value))
    if isinstance(value, float):
        return (2, value)
    return (3, value)


def values_match(a: Cell, b: Cell, tolerance: Tolerance) -> bool:
    a, b = _normalize(a), _normalize(b)
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, float) and isinstance(b, float):
        return abs(a - b) <= max(tolerance.rel * max(abs(a), abs(b)), tolerance.abs)
    return a == b


def _column(result: Result, index: int) -> list[Value]:
    return sorted((_normalize(row[index]) for row in result.rows), key=_order)


def _first_match(candidates: Sequence[int], used: set[int], matches) -> int | None:
    return next((index for index in candidates if index not in used and matches(index)), None)


def compare_results(expected: Result, actual: Result, *, ordered: bool, tolerance: Tolerance = Tolerance()) -> Comparison:
    if len(expected.rows) != len(actual.rows):
        return Comparison(False, f"expected {len(expected.rows)} rows, got {len(actual.rows)}")

    expected_keys = [i for i, column in enumerate(expected.columns) if column.role != "measure"]
    actual_keys = [i for i, column in enumerate(actual.columns) if column.role != "measure"]
    key_map: dict[int, int] = {}
    for index in expected_keys:
        values = _column(expected, index)
        found = _first_match(actual_keys, set(key_map.values()), lambda candidate: _column(actual, candidate) == values)
        if found is None:
            return Comparison(False, f"no column matches key column {expected.columns[index].name}")
        key_map[index] = found

    def expected_key(row) -> tuple:
        return tuple(_normalize(row[index]) for index in expected_keys)

    def actual_key(row) -> tuple:
        return tuple(_normalize(row[key_map[index]]) for index in expected_keys)

    def sort_key(key: tuple, row) -> tuple:
        return tuple(map(_order, key)), tuple(_order(_normalize(value)) for value in row)

    expected_rows, actual_rows = list(expected.rows), list(actual.rows)
    if not ordered:
        expected_rows.sort(key=lambda row: sort_key(expected_key(row), row))
        actual_rows.sort(key=lambda row: sort_key(actual_key(row), row))
    expected_sequence = [expected_key(row) for row in expected_rows]
    actual_sequence = [actual_key(row) for row in actual_rows]
    missing = Counter(expected_sequence) - Counter(actual_sequence)
    if missing:
        return Comparison(False, f"no row matches key {next(iter(missing))}")
    for position, (wanted, got) in enumerate(zip(expected_sequence, actual_sequence, strict=True)):
        if wanted != got:
            return Comparison(False, f"row order differs at row {position}")

    pairs = list(zip(expected_rows, actual_rows, strict=True))
    actual_measures = [i for i, column in enumerate(actual.columns) if column.role == "measure"]
    used: set[int] = set()
    for index, column in enumerate(expected.columns):
        if column.role != "measure":
            continue
        found = _first_match(
            actual_measures, used,
            lambda candidate: all(values_match(want[index], got[candidate], tolerance) for want, got in pairs),
        )
        if found is None:
            return Comparison(False, f"no column matches measure {column.name}")
        used.add(found)
    return Comparison(True)
