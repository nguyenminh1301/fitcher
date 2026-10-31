"""Builders for agent node tests over the synthetic fixture pack."""

from datetime import date
from decimal import Decimal

from conftest import FIXTURE_PACK, SCHEMA_DIR
from fake_llm import FakeLLMClient
from fakes import FakeEmbeddings, FakeRunner, FakeSearch

from app.agent.state import AgentDeps
from app.data.clickhouse import QueryOutput
from app.packs.compiler import CompiledPack, DateCoverage, approved_pack
from app.packs.loader import load_pack

TODAY = date(2026, 1, 15)


def compiled_fixture() -> CompiledPack:
    return CompiledPack(
        pack=approved_pack(load_pack(FIXTURE_PACK, schema_dir=SCHEMA_DIR)),
        generation=1,
        embedding_dimensions=4,
        coverage={
            "widget_sales": DateCoverage(rows=120, min_date="2023-01-02", max_date="2025-06-30"),
            "widget_refunds": DateCoverage(rows=8, min_date="2023-02-01", max_date="2025-05-31"),
        },
        compiled_at="2026-01-01T00:00:00+00:00",
    )


def extraction_reply(**overrides) -> dict:
    """Extraction for "Top 10 best-selling widgets in Q1 2024 compared with Q1 2025"."""
    reply = {
        "metric_terms": [],
        "rank_term": "top widgets",
        "dimension_terms": ["widgets"],
        "periods": [{"kind": "quarter", "year": 2024, "quarter": 1}, {"kind": "quarter", "year": 2025, "quarter": 1}],
        "top_n": 10,
        "compare": True,
        "language": "en",
    }
    return {**reply, **overrides}


def example_hit() -> dict:
    return {"id": "revenue_by_widget", "score": 0.9, "source": {
        "type": "example", "title": "Top 10 widgets by revenue",
        "payload": {"sql": "SELECT widget_name, sum(sale_amount) AS widget_revenue FROM marts.widget_sales GROUP BY widget_name"},
    }}


def default_search(index: str, body: dict) -> list[dict]:
    if index.endswith("_examples"):
        return [example_hit()]
    return []


GOOD_SQL = (
    "SELECT widget_name, sumIf(sale_amount, sold_on >= toDate('2025-01-01') AND sold_on < toDate('2025-04-01')) "
    "AS widget_revenue_q1_2025 FROM marts.widget_sales GROUP BY widget_name ORDER BY widget_revenue_q1_2025 DESC LIMIT 10"
)


def good_output(rows: int = 2) -> QueryOutput:
    return QueryOutput(
        query_id="qid-ok",
        columns=["widget_name", "widget_revenue_q1_2025"],
        types=["String", "Decimal(38, 2)"],
        rows=[(f"Widget {number}", Decimal("10.50")) for number in range(rows)],
    )


def deps(llm_replies: list, runner: FakeRunner | None = None, search=default_search, embeddings=None) -> AgentDeps:
    return AgentDeps(
        llm=FakeLLMClient(llm_replies),
        search=FakeSearch(search_results=search),
        embeddings=embeddings or FakeEmbeddings(),
        runner=runner or FakeRunner(runs=[good_output()]),
        compiled=compiled_fixture(),
        today=TODAY,
    )
