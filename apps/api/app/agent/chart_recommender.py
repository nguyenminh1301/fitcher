"""Choose how a Result is drawn (DECISIONS §6 step 15 and §8).

``recommend_chart`` is the one entry point for every answer and every chart
edit: it takes the result and, for a chart edit, the chart type the user asked
for. The §8 rules, with the requested type used when the data allows it, come
in Phase 9; until then every result is offered as ``table_spec``, the rules'
fallback row, whatever type was asked for. The LLM never writes chart data.
"""

from app.contracts.chart_spec import ChartSpec, ChartType, table_spec
from app.contracts.result import Result


def recommend_chart(result: Result, requested: ChartType | None = None) -> ChartSpec:
    return table_spec(result)
