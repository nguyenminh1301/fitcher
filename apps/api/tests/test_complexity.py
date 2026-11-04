"""The SQL complexity rule over single conditions and over every pack's eval cases."""

from datetime import date
from pathlib import Path

import pytest

from app.agent.complexity import complexity
from app.contracts.query_spec import Filter, Period, QuerySpec
from app.packs.loader import load_pack

ROOT = Path(__file__).resolve().parents[3]
PACKS = sorted(path for path in (ROOT / "packs").iterdir() if path.is_dir() and not path.name.startswith("_"))
Q1 = Period(label="Q1", start=date(2025, 1, 1), end=date(2025, 4, 1))
Q2 = Period(label="Q2", start=date(2025, 4, 1), end=date(2025, 7, 1))


def spec(**fields) -> QuerySpec:
    return QuerySpec(**{"metric_ids": ["revenue"], "periods": [Q1], "dataset": "sales", **fields})


def test_one_metric_one_period_and_no_dimension_is_simple():
    assert complexity(spec()) == "simple"


def test_one_dimension_and_filters_stay_simple():
    filters = [Filter(column="region", op="=", value="north")]
    assert complexity(spec(dimensions=["region"], filters=filters)) == "simple"


@pytest.mark.parametrize("fields", [
    {"metric_ids": ["revenue", "orders"]},
    {"dimensions": ["region", "product"]},
    {"periods": [Q1, Q2]},
    {"periods": [Q1, Q2], "compare": True},
    {"top_n": 5, "rank_by": "revenue"},
], ids=["two metrics", "two dimensions", "two periods", "comparison", "top n"])
def test_each_condition_alone_makes_a_spec_standard(fields):
    assert complexity(spec(**fields)) == "standard"


def _eval_specs(pack_dir: Path) -> list[tuple[str, QuerySpec]]:
    pack = load_pack(pack_dir)
    specs = []
    for case in pack.eval.cases:
        expected = case.expected
        if expected.intent != "data_query" or expected.outcome != "answer" or not expected.metrics:
            continue
        periods = [Period(label=p.label, start=p.start, end=p.end) for p in expected.periods]
        if not periods or expected.dataset is None:
            continue
        specs.append((case.category, QuerySpec(
            metric_ids=expected.metrics, dimensions=expected.columns, periods=periods, top_n=expected.top_n,
            rank_by=expected.rank_by, compare=case.category == "two_period_compare", dataset=expected.dataset,
        )))
    return specs


@pytest.mark.parametrize("pack_dir", PACKS, ids=lambda path: path.name)
def test_eval_comparisons_and_rankings_are_standard_and_some_cases_are_simple(pack_dir: Path):
    specs = _eval_specs(pack_dir)

    assert all(complexity(item) == "standard" for category, item in specs if category in ("two_period_compare", "top_n"))
    assert any(complexity(item) == "simple" for _, item in specs)
