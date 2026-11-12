"""Choose how a Result is drawn by the DECISIONS §8 rules.

The rules read only the result's columns and values and, for a comparison of
periods, the QuerySpec's period labels; they never call an LLM, and the LLM
never writes chart data. ``choose`` returns the ChartSpec of the first row of
the §8 table the data matches, with every type the same ``x``, ``y`` and
``series`` can be drawn as in ``allowed_types``, since the web app switches
type without changing them. A bar and a pie both suit one category and one
measure of at most six non-negative groups; only the question can tell whether
it asks for a share, so ``tied`` names both and the ``chart_recommender`` node
asks the ``fast`` tier.
"""

from dataclasses import dataclass
import re

from app.contracts.chart_spec import ChartSpec, ChartType, table_spec
from app.contracts.query_spec import QuerySpec
from app.contracts.result import ColumnInfo, Result

MAX_BAR_GROUPS = 20
MAX_SERIES = 6
MAX_PIE_GROUPS = 6
# A bar whose longest category label is longer than this is drawn horizontally.
LONG_LABEL = 12


@dataclass(frozen=True)
class ChartChoice:
    spec: ChartSpec
    # The default types the rules cannot tell apart, the rules' pick first; empty when there is no tie.
    tied: tuple[ChartType, ...] = ()

    def drawn_as(self, chart_type: ChartType | None) -> ChartSpec:
        """The spec drawn as ``chart_type`` when the data allows it, otherwise the rules' choice."""
        if chart_type is None or chart_type not in self.spec.allowed_types:
            return self.spec
        return self.spec.model_copy(update={"type": chart_type})


def _values(result: Result, column: ColumnInfo) -> list:
    index = result.columns.index(column)
    return [row[index] for row in result.rows]


def _distinct(result: Result, column: ColumnInfo) -> list:
    return list(dict.fromkeys(_values(result, column)))


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _compared(measures: list[ColumnInfo], query: QuerySpec | None) -> list[ColumnInfo]:
    """The measures drawn side by side: one per compared period when the query has them, else those in the first measure's unit."""
    if query is not None and len(query.periods) > 1:
        per_period = [
            column for period in query.periods for column in measures if column.name.endswith(f"_{_slug(period.label)}")
        ]
        if len(per_period) > 1:
            return per_period
    return [column for column in measures if column.format == measures[0].format]


def _orientation(result: Result, x: ColumnInfo) -> str:
    longest = max((len(str(value)) for value in _values(result, x)), default=0)
    return "horizontal" if longest > LONG_LABEL else "vertical"


def _spec(chart_type: ChartType, x: ColumnInfo, y: list[ColumnInfo], allowed: list[ChartType], **fields) -> ChartSpec:
    return ChartSpec(
        type=chart_type, x=x.name, y=[column.name for column in y], format=y[0].format, allowed_types=[*allowed, "table"],
        **fields,
    )


def _over_time(result: Result, time: ColumnInfo, categories: list[ColumnInfo], measures: list[ColumnInfo]) -> ChartChoice | None:
    """Time + number: a line of at most six series, by a category or by measures in one unit."""
    if len(categories) > 1:
        return None
    if categories:
        y, series, count = measures[:1], categories[0].name, len(_distinct(result, categories[0]))
    else:
        y = _compared(measures, None)
        series, count = None, len(y)
    if count > MAX_SERIES:
        return None
    allowed: list[ChartType] = ["line"]
    if len(_distinct(result, time)) <= MAX_BAR_GROUPS:
        allowed.append("grouped_bar" if count > 1 else "bar")
    orientation = "vertical" if len(allowed) > 1 else None
    return ChartChoice(_spec("line", time, y, allowed, series=series, orientation=orientation))


def _by_category(result: Result, categories: list[ColumnInfo], measures: list[ColumnInfo], query: QuerySpec | None) -> ChartChoice | None:
    """Category + number: a bar, a grouped bar for a comparison group, and a pie when the groups can be a share."""
    if len(categories) == 2:
        series, x = sorted(categories, key=lambda column: len(_distinct(result, column)))
        if len(_distinct(result, x)) > MAX_BAR_GROUPS or len(_distinct(result, series)) > MAX_SERIES:
            return None
        spec = _spec("grouped_bar", x, measures[:1], ["grouped_bar", "bar"], series=series.name, orientation=_orientation(result, x))
        return ChartChoice(spec)
    x = categories[0]
    groups = len(_distinct(result, x))
    if groups > MAX_BAR_GROUPS:
        return None
    y = _compared(measures, query)
    if len(y) > MAX_SERIES:
        return None
    if len(y) > 1:
        return ChartChoice(_spec("grouped_bar", x, y, ["grouped_bar", "bar"], orientation=_orientation(result, x)))
    values = _values(result, y[0])
    share = groups <= MAX_PIE_GROUPS and all(isinstance(value, (int, float)) and value >= 0 for value in values)
    spec = _spec("bar", x, y, ["bar", "pie"] if share else ["bar"], orientation=_orientation(result, x))
    return ChartChoice(spec, ("bar", "pie") if share else ())


def choose(result: Result, query: QuerySpec | None = None) -> ChartChoice:
    measures = [column for column in result.columns if column.role == "measure" and column.type == "number"]
    labels = [column for column in result.columns if column not in measures]
    times = [column for column in labels if column.role == "time" or column.type in ("date", "datetime")]
    categories = [column for column in labels if column not in times]
    choice = None
    if result.rows and measures:
        if len(result.rows) == 1 and len(measures) == 1:
            choice = ChartChoice(_spec("kpi", (labels or measures)[0], measures, ["kpi"]))
        elif not labels and len(measures) > 1 and len(result.rows) > 1:
            choice = ChartChoice(_spec("scatter", measures[0], measures[1:2], ["scatter"]))
        elif len(times) == 1:
            choice = _over_time(result, times[0], categories, measures)
        elif not times and 1 <= len(categories) <= 2:
            choice = _by_category(result, categories, measures, query)
    return choice or ChartChoice(table_spec(result))


def recommend_chart(result: Result, query: QuerySpec | None = None, requested: ChartType | None = None) -> ChartSpec:
    """The chart a type was asked for, when the data allows it, or the rules' choice; a tie keeps the rules' pick."""
    return choose(result, query).drawn_as(requested)
