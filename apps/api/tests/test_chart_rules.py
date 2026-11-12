"""The DECISIONS §8 chart rules: one case per row of the table, plus the limits each row names."""

from datetime import date

import pytest

from app.agent.chart_rules import choose, recommend_chart
from app.contracts.query_spec import Period, QuerySpec
from app.contracts.result import ColumnInfo, Result


def label(name: str) -> ColumnInfo:
    return ColumnInfo(name=name, type="string", role="dimension")


def day(name: str) -> ColumnInfo:
    return ColumnInfo(name=name, type="date", role="time")


def number(name: str, unit: str = "currency") -> ColumnInfo:
    return ColumnInfo(name=name, type="number", role="measure", format=unit)


def result(columns: list[ColumnInfo], rows: list[list]) -> Result:
    return Result(columns=columns, rows=rows, row_count=len(rows))


def months(count: int) -> list[str]:
    return [date(2024, 1 + index % 12, 1).isoformat() for index in range(count)]


def comparison(periods: list[str]) -> QuerySpec:
    return QuerySpec(
        intent="data_query", metric_ids=["widget_revenue"], dimensions=["widget_name"], compare=True, dataset="widget_sales",
        periods=[Period(label=name, start=date(2024 + index, 1, 1), end=date(2024 + index, 4, 1)) for index, name in enumerate(periods)],
    )


KPI = result([number("widget_revenue")], [[1250.0]])
SHARE = result([label("region"), number("widget_revenue")], [["North", 40.0], ["South", 35.0], ["East", 25.0]])
SEVEN_REGIONS = result([label("region"), number("widget_revenue")], [[f"R{index}", 10.0] for index in range(7)])
WITH_A_LOSS = result([label("region"), number("margin")], [["North", 40.0], ["South", -5.0]])
TWENTY = result([label("widget_name"), number("widget_revenue")], [[f"W{index}", 10.0] for index in range(20)])
TWENTY_ONE = result([label("widget_name"), number("widget_revenue")], [[f"W{index}", 10.0] for index in range(21)])
LONG_LABELS = result([label("widget_name"), number("widget_revenue")], [[f"Deluxe stainless widget {index}", 10.0] for index in range(8)])
MONTHLY = result([day("month"), number("widget_revenue")], [[month, 10.0] for month in months(12)])
SIX_LINES = result([day("month"), label("region"), number("widget_revenue")], [[month, f"R{index}", 1.0] for month in months(3) for index in range(6)])
SEVEN_LINES = result([day("month"), label("region"), number("widget_revenue")], [[month, f"R{index}", 1.0] for month in months(3) for index in range(7)])
PERIODS_WIDE = result(
    [label("widget_name"), number("widget_revenue_q1_2024"), number("widget_revenue_q1_2025"), number("widget_revenue_change"), number("widget_revenue_change_pct", "percent")],
    [[f"Widget {index}", 10.0, 12.0, 2.0, 20.0] for index in range(10)],
)
PERIODS_LONG = result(
    [label("period"), label("widget_name"), number("widget_revenue")],
    [[period, f"Widget {index}", 10.0] for period in ("Q1 2024", "Q1 2025") for index in range(10)],
)
TWO_NUMBERS = result([number("widget_price"), number("widgets_sold", "count")], [[9.5, 120], [12.0, 80], [15.0, 40]])
ONE_POINT = result([number("widget_price"), number("widgets_sold", "count")], [[9.5, 120]])
THREE_LABELS = result([label("a"), label("b"), label("c"), number("widget_revenue")], [["x", "y", "z", 1.0], ["x", "y", "w", 2.0]])
ONLY_LABELS = result([label("widget_name")], [["Blue"], ["Green"]])
EMPTY = result([label("widget_name"), number("widget_revenue")], [])


@pytest.mark.parametrize(
    ("data", "query", "expected"),
    [
        pytest.param(KPI, None, {"type": "kpi", "y": ["widget_revenue"], "allowed_types": ["kpi", "table"]}, id="1 row x 1 number is a KPI"),
        pytest.param(MONTHLY, None, {"type": "line", "x": "month", "y": ["widget_revenue"], "series": None, "allowed_types": ["line", "bar", "table"]}, id="time + number is a line"),
        pytest.param(SIX_LINES, None, {"type": "line", "x": "month", "series": "region", "allowed_types": ["line", "grouped_bar", "table"]}, id="a line has at most 6 series"),
        pytest.param(SEVEN_LINES, None, {"type": "table", "allowed_types": ["table"]}, id="7 series over time fall back to the table"),
        pytest.param(TWENTY, None, {"type": "bar", "x": "widget_name", "orientation": "vertical", "allowed_types": ["bar", "table"]}, id="category + number, at most 20 groups, is a bar"),
        pytest.param(TWENTY_ONE, None, {"type": "table", "allowed_types": ["table"]}, id="21 groups fall back to the table"),
        pytest.param(LONG_LABELS, None, {"type": "bar", "orientation": "horizontal"}, id="long labels make the bar horizontal"),
        pytest.param(
            PERIODS_WIDE, comparison(["Q1 2024", "Q1 2025"]),
            {"type": "grouped_bar", "x": "widget_name", "y": ["widget_revenue_q1_2024", "widget_revenue_q1_2025"], "series": None, "format": "currency", "allowed_types": ["grouped_bar", "bar", "table"]},
            id="a measure per compared period is a grouped bar",
        ),
        pytest.param(
            PERIODS_LONG, None,
            {"type": "grouped_bar", "x": "widget_name", "y": ["widget_revenue"], "series": "period", "allowed_types": ["grouped_bar", "bar", "table"]},
            id="category + number + comparison group is a grouped bar",
        ),
        pytest.param(SHARE, None, {"type": "bar", "allowed_types": ["bar", "pie", "table"]}, id="at most 6 non-negative groups also allow a pie"),
        pytest.param(SEVEN_REGIONS, None, {"type": "bar", "allowed_types": ["bar", "table"]}, id="7 groups never allow a pie"),
        pytest.param(WITH_A_LOSS, None, {"type": "bar", "allowed_types": ["bar", "table"]}, id="a negative value never allows a pie"),
        pytest.param(TWO_NUMBERS, None, {"type": "scatter", "x": "widget_price", "y": ["widgets_sold"], "allowed_types": ["scatter", "table"]}, id="number + number is a scatter"),
        pytest.param(ONE_POINT, None, {"type": "table", "allowed_types": ["table"]}, id="one row of two numbers falls back to the table"),
        pytest.param(THREE_LABELS, None, {"type": "table", "allowed_types": ["table"]}, id="three labels fall back to the table"),
        pytest.param(ONLY_LABELS, None, {"type": "table", "allowed_types": ["table"]}, id="no measure falls back to the table"),
        pytest.param(EMPTY, None, {"type": "table", "allowed_types": ["table"]}, id="no rows fall back to the table"),
    ],
)
def test_each_rule_chooses_its_chart(data, query, expected):
    spec = choose(data, query).spec.model_dump()

    assert {key: spec[key] for key in expected} == expected


@pytest.mark.parametrize("data", [MONTHLY, SIX_LINES, SEVEN_LINES])
def test_a_time_series_never_allows_a_pie(data):
    assert "pie" not in choose(data).spec.allowed_types


def test_only_a_bar_that_could_be_a_pie_is_a_tie():
    assert choose(SHARE).tied == ("bar", "pie")
    assert [choose(data).tied for data in (KPI, MONTHLY, TWENTY, SEVEN_REGIONS, PERIODS_WIDE, TWO_NUMBERS)] == [()] * 6


def test_a_chart_without_a_bar_has_no_orientation():
    assert [choose(data).spec.orientation for data in (KPI, TWO_NUMBERS, SEVEN_LINES)] == [None] * 3


def test_a_bar_over_time_stays_vertical():
    assert choose(MONTHLY).spec.orientation == "vertical"


def test_a_requested_type_the_data_allows_is_drawn():
    spec = recommend_chart(SHARE, requested="pie")

    assert (spec.type, spec.allowed_types) == ("pie", ["bar", "pie", "table"])


def test_a_requested_type_the_data_does_not_allow_keeps_the_rules_choice():
    assert recommend_chart(MONTHLY, requested="pie").type == "line"


def test_without_a_request_a_tie_keeps_the_bar():
    assert recommend_chart(SHARE).type == "bar"
