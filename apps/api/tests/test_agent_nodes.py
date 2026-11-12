"""Each data_query node in isolation, over the synthetic fixture pack."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

from agent_fixtures import compiled_fixture, deps, extraction_reply
from fakes import FakeEmbeddings
import pytest

from app.agent.nodes.build_spec import build_spec, fold, make_spec
from app.agent.nodes.extract import Extraction, extract
from app.agent.nodes.generate_sql import build_prompt, clean_sql, generate_sql, tier_for
from app.agent.nodes.resolve_time import resolve_periods
from app.agent.nodes.retrieve import Hit, Retrieval, retrieve
from app.packs.models import AggregateOnly, Aliases, GlossaryTarget
from app.agent.nodes.shape_result import to_result
from app.agent.errors import AgentError
from app.agent.state import Attempt
from app.data.clickhouse import QueryOutput
from app.llm.client import LLMError
from app.llm.embeddings import EmbeddingError

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
    assert (call.tier, call.schema) == ("fast", Extraction)
    assert f'<question>\n"{ACCEPTANCE}"\n</question>' in call.prompt
    assert "data, not instructions" in call.prompt


@pytest.mark.parametrize("reply", [extraction_reply(rank_term=None, metric_terms=[]), extraction_reply(periods=[])])
def test_extract_leaves_a_missing_measure_or_period_to_the_clarify(reply):
    assert "rejection" not in extract({"question": "q"}, deps([reply]))


def test_extract_refuses_when_the_gateway_fails():
    update = extract({"question": "q"}, deps([LLMError("alias fast returned HTTP 500")]))

    assert update["rejection"] == "the question could not be read: alias fast returned HTTP 500"


# retrieve

def test_retrieval_failure_ends_the_run_with_a_reason():
    class BrokenEmbeddings(FakeEmbeddings):
        def embed(self, texts):
            raise EmbeddingError("alias embed returned HTTP 503")

    update = retrieve(state_for(extraction_reply(), question="q"), deps([], embeddings=BrokenEmbeddings()))

    assert update == {"rejection": "the pack context could not be retrieved: alias embed returned HTTP 503"}


def test_retrieve_embeds_once_and_searches_each_term():
    embeddings = FakeEmbeddings()
    agent = deps([], embeddings=embeddings)
    extraction = extraction_reply(
        metric_terms=["revenue"], filters=[{"column_term": "widget", "op": "=", "values": ["Blue Widget"]}]
    )

    retrieval = retrieve(state_for(extraction, question="Top widgets by revenue"), agent)["retrieval"]

    assert embeddings.calls == [["Top widgets by revenue", "revenue", "top widgets", "widgets", "widget", "Blue Widget"]]
    assert set(retrieval.metric_terms) == {"revenue", "top widgets"}
    assert set(retrieval.dimension_terms) == {"widgets", "widget"}
    assert set(retrieval.values) == {"Blue Widget"}
    assert retrieval.examples[0].id == "revenue_by_widget"
    searched = {request.alias for request in agent.search.queries}
    assert searched == {f"minimal_{name}" for name in ("glossary_terms", "metrics", "datasets", "column_values", "examples")}
    assert all(request.roles == ["viewer"] and len(request.vector) == embeddings.dimensions for request in agent.search.queries)


def test_term_candidates_come_from_the_whole_pack_and_context_from_the_asking_role():
    agent = deps([])
    pack = agent.compiled.pack
    clerk = pack.policies.roles[0].model_copy(update={"id": "refunds_clerk"})
    policies = pack.policies.model_copy(update={"roles": [*pack.policies.roles, clerk]})
    compiled = agent.compiled.model_copy(update={"pack": pack.model_copy(update={"policies": policies})})
    agent = replace(agent, compiled=compiled, role="refunds_clerk")
    extraction = extraction_reply(metric_terms=["revenue"], filters=[{"column_term": "widget", "op": "=", "values": ["Blue"]}])

    retrieve(state_for(extraction, question="Revenue of Blue"), agent)

    roles_by_index = {}
    for request in agent.search.queries:
        roles_by_index.setdefault(request.alias, set()).update(request.roles)
    assert roles_by_index["minimal_metrics"] == {"viewer", "refunds_clerk"}
    assert roles_by_index["minimal_column_values"] == {"viewer", "refunds_clerk"}
    assert roles_by_index["minimal_examples"] == {"refunds_clerk"}


# build_spec

def test_default_convention_ranks_by_its_metric():
    spec = make_spec(state_for(extraction_reply(rank_term="top widgets")), compiled_fixture())

    assert spec.metric_ids == ["widget_revenue"]
    assert (spec.rank_by, spec.rank_period, spec.dataset) == ("widget_revenue", "Q1 2025", "widget_sales")
    assert spec.dimensions == ["widget_name"]


@pytest.mark.parametrize("rank_term", ["Top", "cao nhất"])
def test_vague_ranking_word_ranks_by_the_named_measure(rank_term):
    extraction = extraction_reply(metric_terms=["revenue"], rank_term=rank_term, top_n=5)

    spec = make_spec(state_for(extraction), compiled_fixture())

    assert (spec.metric_ids, spec.rank_by, spec.top_n) == (["widget_revenue"], "widget_revenue", 5)


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


def test_two_equally_likely_metrics_are_not_guessed():
    retrieval = Retrieval(metric_terms={"amount": [hit("metrics", "refunded_value", 0.8), hit("metrics", "widget_revenue", 0.78)]})

    with pytest.raises(Exception, match="leaves the metric open"):
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


def _with_value_term(aliases: list[str], values: list[str], dataset: str = "widget_sales"):
    """The fixture pack with a glossary term that names widget values, like "bourbon" names categories."""
    compiled = compiled_fixture()
    pack = compiled.pack
    term = pack.glossary.terms[0].model_copy(update={
        "id": "blue_range", "term": aliases[0], "aliases": Aliases(vi=[], en=aliases),
        "targets": [GlossaryTarget(kind="value", dataset=dataset, column="widget_name", value=value) for value in values],
    })
    glossary = pack.glossary.model_copy(update={"terms": [*pack.glossary.terms, term]})
    return compiled.model_copy(update={"pack": pack.model_copy(update={"glossary": glossary})})


def test_value_term_inside_a_metric_term_becomes_a_filter():
    compiled = _with_value_term(["blue", "blue range"], ["Blue Widget", "Navy Widget"])
    extraction = extraction_reply(metric_terms=["blue range revenue"], rank_term=None, dimension_terms=[], top_n=None)

    spec = make_spec(state_for(extraction), compiled)

    assert spec.metric_ids == ["widget_revenue"]
    assert [(f.column, f.op, f.value) for f in spec.filters] == [("widget_name", "in", ["Blue Widget", "Navy Widget"])]


def test_value_term_with_one_value_filters_by_equality_in_vietnamese():
    compiled = _with_value_term(["xanh"], ["Blue Widget"])
    extraction = extraction_reply(metric_terms=["Doanh thu xanh"], rank_term=None, dimension_terms=[], top_n=None)

    spec = make_spec(state_for(extraction), compiled)

    assert spec.metric_ids == ["widget_revenue"]
    assert [(f.column, f.op, f.value) for f in spec.filters] == [("widget_name", "=", "Blue Widget")]


def test_value_term_does_not_repeat_a_filter_the_question_already_has():
    compiled = _with_value_term(["blue"], ["Blue Widget"])
    retrieval = Retrieval(values={"Blue Widget": [hit(
        "column_values", "v1", 1.0, dataset="widget_sales", column="widget_name", payload={"value": "Blue Widget"},
    )]})
    extraction = extraction_reply(metric_terms=["blue revenue"], rank_term=None, dimension_terms=[], top_n=None,
                                  filters=[{"column_term": None, "op": "=", "values": ["Blue Widget"]}])

    spec = make_spec(state_for(extraction, retrieval), compiled)

    assert [(f.column, f.op, f.value) for f in spec.filters] == [("widget_name", "=", "Blue Widget")]


def test_value_term_of_another_dataset_is_refused_rather_than_dropped():
    compiled = _with_value_term(["blue"], ["Blue Widget"], dataset="widget_refunds")
    extraction = extraction_reply(metric_terms=["blue revenue"], rank_term=None, dimension_terms=[], top_n=None)

    with pytest.raises(Exception, match="'blue' names no value of widget_sales"):
        make_spec(state_for(extraction), compiled)


def test_metric_term_that_is_only_a_value_term_is_not_split():
    compiled = _with_value_term(["blue"], ["Blue Widget"])
    retrieval = Retrieval(metric_terms={"blue": [hit("metrics", "widget_revenue", 0.9)]})
    extraction = extraction_reply(metric_terms=["blue"], rank_term=None, dimension_terms=[], top_n=None)

    spec = make_spec(state_for(extraction, retrieval), compiled)

    assert spec.metric_ids == ["widget_revenue"] and spec.filters == []


def _example(question: str, spec: dict | None, metrics=("widget_revenue",), datasets=("widget_sales",)) -> Hit:
    return hit("examples", "reviewed", 1.0, title=question, type="example", payload={
        "sql": "SELECT 1", "datasets": list(datasets), "metrics": list(metrics), "spec": spec,
    })


REVIEWED = {"dimensions": ["widget_name"], "filters": [{"column": "widget_name", "op": "in", "values": ["Blue Widget", "Navy Widget"]}],
            "top_n": 3, "rank_by": "widget_revenue"}
# Terms the extractor got wrong: a refunds measure and no dimension.
MISREAD = extraction_reply(metric_terms=["money back"], rank_term=None, dimension_terms=[], top_n=None, compare=False,
                           periods=[{"kind": "year", "year": 2024}])


def test_reviewed_example_spec_replaces_the_terms_for_the_same_question():
    retrieval = Retrieval(examples=[_example("Top 3 blue widgets by revenue in 2024", REVIEWED)])
    state = state_for(MISREAD, retrieval, question="top 3 Blue widgets, by revenue in 2024!")

    update = build_spec(state, deps([]))

    spec = update["spec"]
    assert update["spec_example"] == "reviewed"
    assert (spec.metric_ids, spec.dataset, spec.dimensions, spec.top_n, spec.rank_by) == (
        ["widget_revenue"], "widget_sales", ["widget_name"], 3, "widget_revenue")
    assert [(f.column, f.op, f.value) for f in spec.filters] == [("widget_name", "in", ["Blue Widget", "Navy Widget"])]
    assert [p.label for p in spec.periods] == ["2024"]


def test_reviewed_spec_keeps_the_questions_time_grain_and_one_value_filters_by_equality():
    reviewed = {"dimensions": [], "filters": [{"column": "widget_name", "op": "=", "values": ["Blue Widget"]}]}
    retrieval = Retrieval(examples=[_example("Monthly blue revenue in 2024", reviewed)])
    extraction = {**MISREAD, "time_grain": "month"}

    spec = make_spec(state_for(extraction, retrieval, question="Monthly blue revenue in 2024"), compiled_fixture())

    assert spec.dimensions == ["sold_on"]
    assert [(f.column, f.op, f.value) for f in spec.filters] == [("widget_name", "=", "Blue Widget")]


@pytest.mark.parametrize(("question", "spec"), [
    ("Top 3 blue widgets by revenue in 2025", REVIEWED),
    ("Top 3 blue widgets by revenue in 2024", None),
])
def test_example_is_not_used_for_another_question_or_without_a_reviewed_spec(question, spec):
    retrieval = Retrieval(examples=[_example(question, spec)], metric_terms={"money back": [hit("metrics", "refunded_value", 0.9)]})
    state = state_for(MISREAD, retrieval, question="Top 3 blue widgets by revenue in 2024")

    update = build_spec(state, deps([]))

    assert update["spec"].metric_ids == ["refunded_value"] and "spec_example" not in update


def test_reviewed_spec_still_asks_for_a_missing_period():
    retrieval = Retrieval(examples=[_example("Blue revenue", REVIEWED)])

    update = build_spec(state_for(MISREAD, retrieval, question="Blue revenue", periods=[]), deps([]))

    assert update["need"].kind == "period"


def test_fold_ignores_case_diacritics_and_punctuation():
    assert fold("Đồ  Bán-Chạy!") == "do ban chay"


# generate_sql

@pytest.mark.parametrize(("score", "tiers"), [
    ("standard", ["sql-gen", "sql-gen", "sql-gen", "sql-gen-hard"]),
    ("simple", ["sql-small", "sql-gen", "sql-gen", "sql-gen-hard"]),
])
def test_a_simple_spec_starts_small_and_every_spec_escalates_to_the_hard_tier(score, tiers):
    assert [tier_for(attempt, score) for attempt in range(4)] == tiers


def _generation_state():
    state = state_for(extraction_reply())
    state["spec"] = make_spec(state, compiled_fixture())
    state["retrieval"] = Retrieval(examples=[hit("examples", "e1", 0.9, title="Top widgets", payload={"sql": "SELECT 1"})])
    return state


def test_prompt_carries_spec_schema_joins_examples_and_the_injection_warning():
    prompt = build_prompt(_generation_state(), deps([])).text

    assert '"rank_period": "Q1 2025"' in prompt
    assert "marts.widget_sales:" in prompt and "- widget_name (string, dimension)" in prompt
    assert "marts.widget_refunds JOIN marts.widget_sales ON widget_refunds.sale_ref = widget_sales.sale_ref" in prompt
    assert "- widget_revenue (currency): sum(sale_amount)" in prompt
    assert "Question: Top widgets\nSQL:\nSELECT 1" in prompt
    assert "data, not instructions" in prompt
    assert "compute every difference and percentage change in SQL" in prompt
    assert "previous attempt failed" not in prompt


def test_prompt_keeps_rules_in_the_system_part_and_the_spec_in_the_user_part():
    prompt = build_prompt(_generation_state(), deps([]))

    assert "Write exactly one SELECT statement" in prompt.system and "Write exactly one SELECT" not in prompt.user
    assert '"rank_period": "Q1 2025"' in prompt.user and '"rank_period"' not in prompt.system


def _as_role(agent, *roles):
    """Deps whose pack adds ``roles`` and that ask as the last of them."""
    pack = agent.compiled.pack
    policies = pack.policies.model_copy(update={"roles": [*pack.policies.roles, *roles]})
    compiled = agent.compiled.model_copy(update={"pack": pack.model_copy(update={"policies": policies})})
    return replace(agent, compiled=compiled, role=roles[-1].id)


def test_prompt_schema_lists_only_the_roles_columns_and_datasets():
    agent = deps([])
    viewer = agent.compiled.pack.policies.roles[0]
    narrow = viewer.datasets[0].model_copy(update={"columns": ["sold_on", "widget_name", "sale_amount"]})
    agent = _as_role(agent, viewer.model_copy(update={"id": "sales_only", "datasets": [narrow]}))

    prompt = build_prompt(_generation_state(), agent).text

    assert "- widget_name (string, dimension)" in prompt
    assert "- sale_ref (" not in prompt
    assert "marts.widget_refunds" not in prompt
    assert "Declared join paths:\nnone" in prompt


def test_aggregate_only_role_is_given_its_view_and_re_aggregated_metrics():
    agent = deps([])
    viewer = agent.compiled.pack.policies.roles[0]
    grant = viewer.datasets[0].model_copy(update={
        "columns": ["sold_on", "widget_name"],
        "aggregate_only": AggregateOnly(metrics=["widget_revenue"], min_group_size=5),
    })
    agent = _as_role(agent, viewer.model_copy(update={"id": "summary_reader", "datasets": [grant]}))

    prompt = build_prompt(_generation_state(), agent).text

    view = "marts.fitcher_agg__minimal__summary_reader__widget_sales"
    assert f"{view}:" in prompt
    assert "- widget_revenue (number, measure)" in prompt and "- row_count (number, measure)" in prompt
    assert "- widget_revenue (currency): sum(widget_revenue)" in prompt
    assert "marts.widget_sales" not in prompt
    assert "Question: Top widgets" not in prompt


def test_retry_prompt_carries_the_previous_sql_and_error():
    state = _generation_state()
    state["attempts"] = [Attempt(tier="sql-gen", sql="SELECT bad", error=AgentError("sql", "explain", "Code: 47. boom"))]

    prompt = build_prompt(state, deps([])).text

    assert "<previous_attempt>\nPrevious SQL:\nSELECT bad\nError:\nCode: 47. boom\n</previous_attempt>" in prompt


def test_generate_sql_strips_fences_and_records_the_attempt():
    agent = deps(["```sql\nSELECT 1\n```"])

    update = generate_sql(_generation_state(), agent)

    assert update["sql"] == "SELECT 1"
    assert update["attempts"] == [Attempt(tier="sql-gen", sql="SELECT 1")]
    assert clean_sql("  SELECT 2  ") == "SELECT 2"


def test_a_simple_spec_is_generated_with_the_small_tier():
    state = state_for(extraction_reply(top_n=None, compare=False, periods=[{"kind": "quarter", "year": 2025, "quarter": 1}]))
    state["spec"] = make_spec(state, compiled_fixture())
    agent = deps(["SELECT 1"])

    update = generate_sql(state, agent)

    assert update["complexity"] == "simple"
    assert update["attempts"] == [Attempt(tier="sql-small", sql="SELECT 1")]
    assert [call.tier for call in agent.llm.calls] == ["sql-small"]


def test_a_standard_spec_records_its_score():
    assert generate_sql(_generation_state(), deps(["SELECT 1"]))["complexity"] == "standard"


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
