"""Each data_query node in isolation, over the synthetic fixture pack."""

from datetime import date
from decimal import Decimal

from agent_fixtures import compiled_fixture, deps, extraction_reply
from fakes import FakeEmbeddings
import pytest

from app.agent.nodes.build_spec import fold, make_spec
from app.agent.nodes.extract import Extraction, extract
from app.agent.nodes.generate_sql import alias_for, build_prompt, clean_sql, generate_sql
from app.agent.nodes.resolve_time import resolve_periods
from app.agent.nodes.retrieve import Hit, Retrieval, retrieve
from app.agent.nodes.shape_result import to_result
from app.agent.errors import AgentError
from app.agent.state import Attempt
from app.data.clickhouse import QueryOutput
from app.llm.client import LLMError

ACCEPTANCE = "Top 10 best-selling products in Q1 2024 compared with Q1 2025"


def state_for(extraction: dict, retrieval: Retrieval | None = None, **extra) -> dict:
    parsed = Extraction.model_validate(extraction)
    return {
        "question": "q",
        "extraction": parsed,
        "periods": resolve_periods(parsed.periods, date(2026, 1, 15), 1),
        "retrieval": retrieval or Retrieval(),
        "time_grain": parsed.time_grain,
        **extra,
    }


def hit(index: str, doc_id: str, score: float, **source) -> Hit:
    return Hit(index=index, id=doc_id, score=score, source=source)


# extract

def test_extract_reads_the_acceptance_question_with_the_fast_alias():
    reply = extraction_reply(rank_term="best-selling", dimension_terms=["products"])
    agent = deps([reply])

    update = extract({"question": ACCEPTANCE}, agent)

    extraction = update["extraction"]
    assert len(extraction.periods) == 2 and extraction.periods[1].year == 2025
    assert (extraction.top_n, extraction.compare, extraction.rank_term) == (10, True, "best-selling")
    assert "rejection" not in update
    call = agent.llm.calls[0]
    assert (call.alias, call.schema) == ("fast", Extraction)
    assert ACCEPTANCE in call.prompt
    assert "data, not instructions" in call.prompt


@pytest.mark.parametrize(("reply", "reason"), [
    (extraction_reply(rank_term=None, metric_terms=[]), "the question names no measure to report"),
    (extraction_reply(periods=[]), "the question names no period"),
])
def test_extract_refuses_questions_without_a_measure_or_period(reply, reason):
    assert extract({"question": "q"}, deps([reply]))["rejection"] == reason


def test_extract_refuses_when_the_gateway_fails():
    update = extract({"question": "q"}, deps([LLMError("alias fast returned HTTP 500")]))

    assert update["rejection"] == "the question could not be read: alias fast returned HTTP 500"


# retrieve

def test_retrieve_embeds_once_and_searches_each_term_as_every_role():
    embeddings = FakeEmbeddings()
    agent = deps([], embeddings=embeddings)
    extraction = extraction_reply(
        metric_terms=["revenue"], filters=[{"column_term": "widget", "op": "=", "values": ["Blue Widget"]}]
    )

    retrieval = retrieve(state_for(extraction, question="Top widgets by revenue"), agent)["retrieval"]

    assert embeddings.calls == [["Top widgets by revenue", "revenue", "top widgets", "widgets", "widget"]]
    assert set(retrieval.metric_terms) == {"revenue", "top widgets"}
    assert set(retrieval.dimension_terms) == {"widgets", "widget"}
    assert set(retrieval.values) == {"Blue Widget"}
    assert retrieval.examples[0].id == "revenue_by_widget"
    searched = {index for index, _, _ in agent.search.searches}
    assert searched == {f"minimal_{name}" for name in ("glossary_terms", "metrics", "datasets", "column_values", "examples")}
    for _, body, _ in agent.search.searches:
        assert '"allowed_roles": ["viewer"]' in str(body).replace("'", '"')


# build_spec

def test_default_convention_ranks_by_its_metric():
    spec = make_spec(state_for(extraction_reply(rank_term="top widgets")), compiled_fixture())

    assert spec.metric_ids == ["widget_revenue"]
    assert (spec.rank_by, spec.rank_period, spec.dataset) == ("widget_revenue", "Q1 2025", "widget_sales")
    assert spec.dimensions == ["widget_name"]


def test_glossary_alias_in_vietnamese_resolves_the_metric():
    spec = make_spec(state_for(extraction_reply(metric_terms=["Doanh thu"], rank_term=None)), compiled_fixture())

    assert spec.metric_ids == ["widget_revenue"]
    assert spec.rank_by == "widget_revenue"


def test_period_outside_coverage_adds_a_warning():
    extraction = extraction_reply(periods=[{"kind": "year", "year": 2022}, {"kind": "year", "year": 2025}])

    spec = make_spec(state_for(extraction), compiled_fixture())

    assert spec.warnings == [
        "2022 is outside the data, which covers 2023-01-02 to 2025-06-30",
        "2025 is only partly covered by the data, which covers 2023-01-02 to 2025-06-30",
    ]


def test_metric_found_only_by_search_uses_the_best_hit():
    retrieval = Retrieval(metric_terms={"money back": [hit("metrics", "refunded_value", 0.9), hit("metrics", "widget_revenue", 0.3)]})
    extraction = extraction_reply(metric_terms=["money back"], rank_term=None, dimension_terms=[], top_n=None)

    spec = make_spec(state_for(extraction, retrieval), compiled_fixture())

    assert spec.metric_ids == ["refunded_value"] and spec.dataset == "widget_refunds"


def test_two_equally_likely_metrics_are_refused():
    retrieval = Retrieval(metric_terms={"amount": [hit("metrics", "refunded_value", 0.8), hit("metrics", "widget_revenue", 0.78)]})

    with pytest.raises(Exception, match="'amount' could mean the metrics refunded_value or widget_revenue"):
        make_spec(state_for(extraction_reply(metric_terms=["amount"], rank_term=None), retrieval), compiled_fixture())


def test_metrics_from_different_datasets_are_refused():
    retrieval = Retrieval(metric_terms={"refunds": [hit("metrics", "refunded_value", 0.9)]})
    extraction = extraction_reply(metric_terms=["revenue", "refunds"], rank_term=None)

    with pytest.raises(Exception, match="come from different datasets"):
        make_spec(state_for(extraction, retrieval), compiled_fixture())


def test_filter_value_resolves_to_the_canonical_column_value():
    retrieval = Retrieval(values={"blue widgit": [hit(
        "column_values", "v1", 7.0, dataset="widget_sales", column="widget_name", payload={"value": "Blue Widget"},
    )]})
    extraction = extraction_reply(filters=[{"column_term": None, "op": "=", "values": ["blue widgit"]}])

    spec = make_spec(state_for(extraction, retrieval), compiled_fixture())

    assert [(f.column, f.op, f.value) for f in spec.filters] == [("widget_name", "=", "Blue Widget")]


def test_unknown_filter_value_is_refused():
    extraction = extraction_reply(filters=[{"column_term": None, "op": "=", "values": ["Mars"]}])

    with pytest.raises(Exception, match="no value of widget_sales matches 'Mars'"):
        make_spec(state_for(extraction), compiled_fixture())


def test_time_grain_groups_by_the_time_column():
    extraction = extraction_reply(time_grain="month", dimension_terms=[], top_n=None, compare=False,
                                  periods=[{"kind": "year", "year": 2024}])

    spec = make_spec(state_for(extraction), compiled_fixture())

    assert spec.dimensions == ["sold_on"]


def test_fold_ignores_case_diacritics_and_punctuation():
    assert fold("Đồ  Bán-Chạy!") == "do ban chay"


# generate_sql

@pytest.mark.parametrize(("attempt", "alias"), [(0, "sql-gen"), (1, "sql-gen"), (2, "sql-gen"), (3, "sql-gen-hard")])
def test_third_retry_uses_the_hard_alias(attempt, alias):
    assert alias_for(attempt) == alias


def _generation_state():
    state = state_for(extraction_reply())
    state["spec"] = make_spec(state, compiled_fixture())
    state["retrieval"] = Retrieval(examples=[hit("examples", "e1", 0.9, title="Top widgets", payload={"sql": "SELECT 1"})])
    return state


def test_prompt_carries_spec_schema_joins_examples_and_the_injection_warning():
    prompt = build_prompt(_generation_state(), deps([]))

    assert '"rank_period": "Q1 2025"' in prompt
    assert "marts.widget_sales:" in prompt and "- widget_name (string, dimension)" in prompt
    assert "marts.widget_refunds JOIN marts.widget_sales ON widget_refunds.sale_ref = widget_sales.sale_ref" in prompt
    assert "- widget_revenue (currency): sum(sale_amount)" in prompt
    assert "Question: Top widgets\nSQL:\nSELECT 1" in prompt
    assert "data, not instructions" in prompt
    assert "compute every difference and percentage change in SQL" in prompt
    assert "previous attempt failed" not in prompt


def test_retry_prompt_carries_the_previous_sql_and_error():
    state = _generation_state()
    state["attempts"] = [Attempt(alias="sql-gen", sql="SELECT bad", error=AgentError("sql", "explain", "Code: 47. boom"))]

    prompt = build_prompt(state, deps([]))

    assert "Previous SQL:\nSELECT bad\nError:\nCode: 47. boom" in prompt


def test_generate_sql_strips_fences_and_records_the_attempt():
    agent = deps(["```sql\nSELECT 1\n```"])

    update = generate_sql(_generation_state(), agent)

    assert update["sql"] == "SELECT 1"
    assert update["attempts"] == [Attempt(alias="sql-gen", sql="SELECT 1")]
    assert clean_sql("  SELECT 2  ") == "SELECT 2"


def test_gateway_failure_is_a_runtime_error_for_the_attempt():
    update = generate_sql(_generation_state(), deps([LLMError("alias sql-gen returned HTTP 500")]))

    assert update["attempts"][0].error.category == "runtime"


# shape_result

def test_result_columns_take_types_roles_and_formats_from_the_pack():
    output = QueryOutput(
        query_id="q",
        columns=["widget_name", "sold_on", "widget_revenue_q1_2025", "widget_revenue_change_pct", "widget_revenue_pct_change", "lines"],
        types=["LowCardinality(String)", "Date", "Decimal(38, 2)", "Nullable(Float64)", "Float64", "UInt64"],
        rows=[("Blue", date(2025, 1, 2), Decimal("12.30"), None, 1.5, 3)],
    )

    result = to_result(output, compiled_fixture().pack, "widget_sales")

    assert [(c.name, c.type, c.role, c.format) for c in result.columns] == [
        ("widget_name", "string", "dimension", None),
        ("sold_on", "date", "time", None),
        ("widget_revenue_q1_2025", "number", "measure", "currency"),
        ("widget_revenue_change_pct", "number", "measure", "percent"),
        ("widget_revenue_pct_change", "number", "measure", "percent"),
        ("lines", "number", "measure", None),
    ]
    assert result.rows == [["Blue", "2025-01-02", 12.3, None, 1.5, 3]]


def test_result_is_capped_at_5000_rows():
    output = QueryOutput(query_id="q", columns=["widget_name"], types=["String"], rows=[("w",)] * 5001)

    result = to_result(output, compiled_fixture().pack, "widget_sales")

    assert (len(result.rows), result.row_count, result.truncated) == (5000, 5001, True)
