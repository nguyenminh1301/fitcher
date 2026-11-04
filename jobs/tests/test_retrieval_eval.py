"""The retrieval measurement: labelled queries, recall and nDCG, on fake search and embeddings."""

import math
from pathlib import Path

import pytest

from app.eval.cases import load_eval_set
from app.packs.compiler import approved_pack
from app.packs.loader import load_pack
from app.packs.models import EvalCase, EvalExpected
from app.packs.search_indices import value_id
from jobs import retrieval_eval as job

ROOT = Path(__file__).resolve().parents[2]


def case(**updates) -> EvalCase:
    base = EvalCase(
        id="c1", question="Net sales by region", language="en", category="string_filter", role="analyst",
        expected=EvalExpected(intent="data_query", outcome="answer", metrics=["net_sales"], dataset="sales", columns=["region"]),
        expected_sql="SELECT 1", status="approved", evidence=[{"kind": "manual", "ref": "t"}], confidence=1.0,
        expected_sources=["column_values:sales.region=West"],
    )
    return base.model_copy(update=updates)


def test_a_data_case_labels_its_dataset_columns_metrics_and_sources():
    queries = {query.index: query for query in job.labelled_queries([case()])}

    assert queries["datasets"].expected == ("sales", "sales.region")
    assert queries["metrics"].expected == ("net_sales",)
    assert queries["column_values"].expected == (value_id("sales", "region", "West"),)
    assert {query.role for query in queries.values()} == {"analyst"}


def test_a_denied_case_is_not_a_retrieval_label():
    denied = case(expected=EvalExpected(intent="data_query", outcome="deny", metrics=["net_sales"], dataset="sales"), expected_sources=[])
    assert job.labelled_queries([denied]) == []


class Search:
    def __init__(self, ranked):
        self.ranked = ranked
        self.calls = []

    def query(self, alias, text, vector, roles, size):
        self.calls.append((alias, roles, size))
        return [{"id": doc, "score": 1.0, "source": {}} for doc in self.ranked.get(alias, [])]


class Embeddings:
    dimensions = 2

    def __init__(self):
        self.calls = []

    def embed(self, texts):
        self.calls.append(list(texts))
        return [[0.0, 1.0] for _ in texts]


def test_recall_and_ndcg_per_collection_and_language():
    queries = job.labelled_queries([case(), case(id="c2", language="vi", question="Doanh thu theo vùng")])
    filler = [f"x{n}" for n in range(5)]
    search = Search({"shop_datasets": ["sales", *filler, "sales.region"], "shop_metrics": ["net_sales"]})
    embeddings = Embeddings()

    report = job.totals(job.measure(search, embeddings, "shop", queries))

    assert embeddings.calls == [["Net sales by region", "Doanh thu theo vùng"]]
    assert all(size == job.TOP_K for _, _, size in search.calls)
    datasets = report["datasets"]["all"]
    assert (datasets.queries, datasets.recall_5, datasets.recall_10) == (2, 0.5, 1.0)
    # sales at rank 1 and sales.region at rank 7 (gain 1/log2(8)) against the ideal ranks 1 and 2.
    assert datasets.ndcg_10 == pytest.approx((1 + 1 / 3) / (1 + 1 / math.log2(3)))
    assert report["metrics"]["en"].ndcg_10 == 1.0
    assert report["column_values"]["all"].recall_5 == 0.0
    text = job.render(report, "fake")
    assert "| datasets | all | 2 | 0.500 | 1.000 |" in text
    assert "- column_values / c1: " in text
    before = {"collections": {"metrics": {"all": {"recall_5": 0.5, "ndcg_10": 0.25}}}}
    assert "| metrics | all | 0.500 | 1.000 | 0.250 | 1.000 |" in job.compare(before, report)


def test_every_pack_eval_label_names_an_item_of_the_pack():
    pack = approved_pack(load_pack(ROOT / "packs" / "ecommerce_twin"))
    known = {
        "glossary_terms": {term.id for term in pack.glossary.terms},
        "metrics": {metric.id for metric in pack.metrics.metrics},
        "datasets": {dataset.id for dataset in pack.datasets.datasets}
        | {f"{dataset.id}.{column.name}" for dataset in pack.datasets.datasets for column in dataset.columns},
    }
    queries = job.labelled_queries(load_eval_set(pack).cases)
    assert {query.lang for query in queries if query.index == "glossary_terms"} == {"en", "vi"}
    unknown = [(query.case_id, doc) for query in queries if query.index in known for doc in query.expected if doc not in known[query.index]]
    assert unknown == []
