"""QuerySpec and Result validation (DECISIONS §7)."""

from datetime import date

from pydantic import ValidationError
import pytest

from app.contracts.query_spec import Filter, Period, QuerySpec
from app.contracts.result import ColumnInfo, Result

Q1_2024 = {"label": "Q1 2024", "start": "2024-01-01", "end": "2024-04-01"}
Q1_2025 = {"label": "Q1 2025", "start": "2025-01-01", "end": "2025-04-01"}


def spec(**overrides) -> QuerySpec:
    data = {
        "metric_ids": ["widget_revenue"],
        "dimensions": ["widget_name"],
        "periods": [Q1_2024, Q1_2025],
        "filters": [{"column": "region", "op": "=", "value": "West"}],
        "top_n": 10,
        "rank_by": "widget_revenue",
        "rank_period": "Q1 2025",
        "compare": True,
        "dataset": "widget_sales",
    }
    return QuerySpec.model_validate({**data, **overrides})


def test_decisions_example_round_trips_through_json():
    original = spec()

    restored = QuerySpec.model_validate_json(original.model_dump_json())

    assert restored == original
    assert restored.intent == "data_query"
    assert restored.periods[0].start == date(2024, 1, 1)
    assert original.model_dump(mode="json")["periods"][1] == Q1_2025


def test_period_is_half_open():
    with pytest.raises(ValidationError, match="must be before end"):
        Period(label="empty", start=date(2024, 4, 1), end=date(2024, 4, 1))


@pytest.mark.parametrize("top_n", [0, -1, 1001])
def test_top_n_bounds(top_n):
    with pytest.raises(ValidationError, match="top_n"):
        spec(top_n=top_n)


def test_top_n_is_optional():
    assert spec(top_n=None).top_n is None


@pytest.mark.parametrize(("op", "value"), [("in", ["West", "East"]), ("not in", ["West"]), (">=", 5), ("!=", True)])
def test_known_operators(op, value):
    assert Filter(column="region", op=op, value=value).op == op


@pytest.mark.parametrize(("op", "value", "message"), [
    ("LIKE", "W%", "op"),
    ("in", "West", "non-empty list"),
    ("in", [], "non-empty list"),
    ("=", ["West"], "single value"),
])
def test_invalid_filters(op, value, message):
    with pytest.raises(ValidationError, match=message):
        Filter(column="region", op=op, value=value)


@pytest.mark.parametrize(("overrides", "message"), [
    ({"metric_ids": []}, "metric_ids"),
    ({"periods": []}, "periods"),
    ({"rank_by": "other_metric"}, "rank_by"),
    ({"rank_period": "Q2 2025"}, "rank_period"),
    ({"periods": [Q1_2024], "rank_period": None}, "compare needs at least two periods"),
    ({"periods": [Q1_2024, {**Q1_2025, "label": "Q1 2024"}], "rank_period": None}, "unique"),
    ({"intent": "chart_edit"}, "intent"),
    ({"dataset": ""}, "dataset"),
    ({"surprise": 1}, "surprise"),
])
def test_inconsistent_specs_are_rejected(overrides, message):
    with pytest.raises(ValidationError, match=message):
        spec(**overrides)


def columns() -> list[ColumnInfo]:
    return [
        ColumnInfo(name="period", type="string", role="dimension"),
        ColumnInfo(name="widget_name", type="string", role="dimension"),
        ColumnInfo(name="widget_revenue", type="number", role="measure", format="currency"),
    ]


def test_result_matches_the_decisions_example():
    result = Result(columns=columns(), rows=[["Q1 2025", "Blue", 12345.6]], row_count=1)

    assert result.truncated is False
    assert result.model_dump()["columns"][2]["format"] == "currency"


def test_decisions_example_with_an_abbreviated_row_list_is_valid():
    # DECISIONS §7 shows one of 20 rows with truncated false; names follow the fixture pack.
    result = Result.model_validate({
        "columns": [
            {"name": "period", "type": "string", "role": "dimension"},
            {"name": "widget_name", "type": "string", "role": "dimension"},
            {"name": "widget_revenue", "type": "number", "role": "measure", "format": "currency"},
        ],
        "rows": [["Q1 2025", "Widget A", 12345.6]],
        "row_count": 20,
        "truncated": False,
    })

    assert result.row_count == 20


def test_truncated_result_reports_the_full_row_count():
    result = Result(columns=columns(), rows=[["Q1 2025", "Blue", 1.0]], row_count=20, truncated=True)

    assert result.row_count == 20


@pytest.mark.parametrize(("rows", "row_count", "truncated", "message"), [
    ([["Q1 2025", "Blue"]], 1, False, "2 cells for 3 columns"),
    ([["Q1 2025", "Blue", 1.0]], 0, False, "less than"),
    ([["Q1 2025", "Blue", 1.0]], 1, True, "truncated"),
])
def test_inconsistent_results_are_rejected(rows, row_count, truncated, message):
    with pytest.raises(ValidationError, match=message):
        Result(columns=columns(), rows=rows, row_count=row_count, truncated=truncated)


def test_result_rows_are_capped_at_5000():
    with pytest.raises(ValidationError, match="5000"):
        Result(columns=columns()[:1], rows=[["x"]] * 5001, row_count=5001, truncated=False)


def test_duplicate_column_names_are_rejected():
    with pytest.raises(ValidationError, match="unique"):
        Result(columns=[*columns(), columns()[0]], rows=[], row_count=0)
