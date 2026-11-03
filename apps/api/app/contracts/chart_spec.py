"""ChartSpec: how the web app draws a Result (DECISIONS §7 and §8).

``app.agent.chart_rules`` chooses the spec of every answer and chart
edit by the DECISIONS §8 rules; ``table_spec`` is their fallback row. The LLM
never writes chart data: a ChartSpec only names result columns.
"""

from typing import Literal, Self

from pydantic import Field, model_validator

from app.contracts.query_spec import ContractModel
from app.contracts.result import Result, ValueFormat

ChartType = Literal["bar", "line", "pie", "scatter", "kpi", "table", "grouped_bar"]


class ChartSpec(ContractModel):
    type: ChartType
    x: str = Field(min_length=1)
    y: list[str]
    series: str | None = None
    sort: Literal["asc", "desc"] | None = None
    format: ValueFormat | None = None
    # How a bar is laid out: horizontal when its labels are long (DECISIONS §8); unset for other types.
    orientation: Literal["vertical", "horizontal"] | None = None
    # Every type valid for the data; the web app disables the others (DECISIONS §8).
    allowed_types: list[ChartType] = Field(min_length=1)

    @model_validator(mode="after")
    def _type_is_allowed(self) -> Self:
        if self.type not in self.allowed_types:
            raise ValueError(f"type {self.type!r} must be one of allowed_types {self.allowed_types}")
        return self


def table_spec(result: Result) -> ChartSpec:
    """The table every result can be shown as: the first non-measure column as ``x``, the measures as ``y``."""
    measures = [column for column in result.columns if column.role == "measure"]
    labels = [column for column in result.columns if column.role != "measure"]
    return ChartSpec(
        type="table", x=(labels or result.columns)[0].name, y=[column.name for column in measures],
        format=measures[0].format if measures else None, allowed_types=["table"],
    )
