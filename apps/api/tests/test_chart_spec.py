"""The ChartSpec contract and the table every result can be shown as (DECISIONS §7 and §8)."""

from pydantic import ValidationError
import pytest

from app.contracts.chart_spec import ChartSpec, table_spec
from app.contracts.result import ColumnInfo, Result


def test_the_type_must_be_one_of_the_allowed_types():
    with pytest.raises(ValidationError, match="allowed_types"):
        ChartSpec(type="pie", x="region", y=["sales"], allowed_types=["bar", "table"])


def test_a_full_chart_spec_is_valid():
    spec = ChartSpec.model_validate({
        "type": "bar", "x": "widget_name", "y": ["widget_revenue"], "series": "period", "sort": "desc",
        "format": "currency", "allowed_types": ["grouped_bar", "bar", "table"],
    })

    assert spec.series == "period"


def test_the_table_spec_puts_the_first_label_column_on_x_and_the_measures_on_y():
    result = Result(columns=[
        ColumnInfo(name="sales", type="number", role="measure", format="currency"),
        ColumnInfo(name="period", type="string", role="dimension"),
        ColumnInfo(name="units", type="number", role="measure", format="count"),
    ], rows=[[1.0, "Q1", 2]], row_count=1)

    spec = table_spec(result)

    assert spec.model_dump() == {
        "type": "table", "x": "period", "y": ["sales", "units"], "series": None, "sort": None,
        "format": "currency", "orientation": None, "allowed_types": ["table"],
    }


def test_a_result_of_measures_only_uses_its_first_column_as_x():
    result = Result(columns=[ColumnInfo(name="total", type="number", role="measure")], rows=[[3]], row_count=1)

    assert (table_spec(result).x, table_spec(result).y) == ("total", ["total"])


def test_a_bar_may_carry_its_orientation_and_other_specs_leave_it_unset():
    bar = ChartSpec(type="bar", x="region", y=["sales"], orientation="horizontal", allowed_types=["bar", "table"])

    assert (bar.orientation, table_spec(Result(columns=[ColumnInfo(name="n", type="number", role="measure")], rows=[[1]], row_count=1)).orientation) == ("horizontal", None)


def test_an_unknown_orientation_is_rejected():
    with pytest.raises(ValidationError, match="orientation"):
        ChartSpec(type="bar", x="region", y=["sales"], orientation="diagonal", allowed_types=["bar"])
