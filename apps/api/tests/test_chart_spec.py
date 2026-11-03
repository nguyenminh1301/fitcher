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
        "format": "currency", "allowed_types": ["table"],
    }


def test_a_result_of_measures_only_uses_its_first_column_as_x():
    result = Result(columns=[ColumnInfo(name="total", type="number", role="measure")], rows=[[3]], row_count=1)

    assert (table_spec(result).x, table_spec(result).y) == ("total", ["total"])
