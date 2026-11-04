"""Score a QuerySpec as simple or standard for SQL model routing (DECISIONS §6 step 9, §14).

A spec is simple when it has one metric, at most one dimension, one period,
no comparison and no top N. The one-dataset condition always holds: a
QuerySpec names a single dataset and ``build_spec`` refuses metrics from
different datasets. A grouping by time counts as a dimension, because
``build_spec`` adds the time column to the dimensions. The rule is
deterministic and may be widened only when the pack eval does not regress.
"""

from typing import Literal

from app.contracts.query_spec import QuerySpec

Complexity = Literal["simple", "standard"]


def complexity(spec: QuerySpec) -> Complexity:
    simple = (
        len(spec.metric_ids) == 1
        and len(spec.dimensions) <= 1
        and len(spec.periods) == 1
        and not spec.compare
        and spec.top_n is None
    )
    return "simple" if simple else "standard"
