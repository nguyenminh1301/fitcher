"""Clarify: an ambiguous question asks which measure, column or period it means (DECISIONS §6 step 8)."""

from dataclasses import replace

from agent_fixtures import compiled_fixture, deps, extraction_reply, routing_reply
import pytest
from test_agent_nodes import hit, state_for

from app.agent.graph import run_question
from app.agent.nodes.build_spec import build_spec
from app.agent.nodes.clarify import Need, clarification
from app.agent.nodes.extract import Extraction
from app.agent.nodes.gate import gate, may_read_metric
from app.agent.nodes.retrieve import Retrieval

QUESTION = "Top 10 best-selling widgets in Q1 2024 compared with Q1 2025"


def pack_with_two_columns_for_one_term():
    """The fixture pack, with "item" also naming the refunds' sale_ref column."""
    compiled = compiled_fixture()
    glossary = compiled.pack.glossary
    widget = next(term for term in glossary.terms if term.id == "widget")
    item = widget.model_copy(update={"id": "item", "term": "item", "aliases": widget.aliases.model_copy(update={"en": ["item"], "vi": []})})
    sale_ref = item.targets[0].model_copy(update={"column": "sale_ref"})
    item = item.model_copy(update={"targets": [*item.targets, sale_ref]})
    pack = compiled.pack.model_copy(update={"glossary": glossary.model_copy(update={"terms": [*glossary.terms, item]})})
    return compiled.model_copy(update={"pack": pack})


def refunds_clerk(compiled):
    """The fixture pack plus a role that may read refunds only."""
    viewer = compiled.pack.policies.roles[0]
    clerk = viewer.model_copy(update={"id": "refunds_clerk", "datasets": viewer.datasets[1:]})
    policies = compiled.pack.policies.model_copy(update={"roles": [viewer, clerk]})
    return compiled.model_copy(update={"pack": compiled.pack.model_copy(update={"policies": policies})})


# build_spec records what is missing

def test_a_vague_ranking_word_needs_a_measure_from_its_hits():
    retrieval = Retrieval(metric_terms={"best": [hit("metrics", "widget_revenue", 0.7), hit("metrics", "refunded_value", 0.4)]})

    update = build_spec(state_for(extraction_reply(rank_term="best"), retrieval), deps([]))

    assert update == {"need": Need(kind="metric", term="best", candidates=["widget_revenue", "refunded_value"])}


def test_a_convention_answers_without_clarify():
    update = build_spec(state_for(extraction_reply(rank_term="top widgets")), deps([]))

    assert update["spec"].rank_by == "widget_revenue" and "need" not in update


def test_no_measure_needs_one_from_the_question_hits():
    retrieval = Retrieval(question_metrics=[hit("metrics", "refunded_value", 0.6)])
    extraction = extraction_reply(metric_terms=[], rank_term=None)

    update = build_spec(state_for(extraction, retrieval), deps([]))

    assert update == {"need": Need(kind="metric", candidates=["refunded_value"])}


def test_two_equally_likely_metrics_need_a_choice_between_them():
    retrieval = Retrieval(metric_terms={"amount": [hit("metrics", "refunded_value", 0.8), hit("metrics", "widget_revenue", 0.78)]})

    update = build_spec(state_for(extraction_reply(metric_terms=["amount"], rank_term=None), retrieval), deps([]))

    assert update == {"need": Need(kind="metric", term="amount", candidates=["refunded_value", "widget_revenue"])}


def test_an_ambiguous_column_needs_a_choice_between_its_columns():
    compiled = pack_with_two_columns_for_one_term()
    extraction = extraction_reply(dimension_terms=["item"])

    update = build_spec(state_for(extraction), replace(deps([]), compiled=compiled))

    assert update == {"need": Need(kind="column", term="item", candidates=["widget_sales.widget_name", "widget_sales.sale_ref"])}


def test_a_missing_period_is_needed_after_the_measure():
    parsed = Extraction.model_validate(extraction_reply(periods=[]))
    state = {"question": "q", "extraction": parsed, "periods": [], "retrieval": Retrieval(), "time_grain": None}

    assert build_spec(state, deps([])) == {"need": Need(kind="period")}


# clarification: the question and its options

def readable(metric_id: str) -> bool:
    return True


def test_a_measure_clarification_offers_metric_names_with_stable_ids():
    need = Need(kind="metric", term="best", candidates=["widget_revenue", "refunded_value"])

    asked = clarification(need, "en", compiled_fixture().pack, readable)

    assert asked.question == 'Which measure do you mean by "best"?'
    assert [(option.id, option.label) for option in asked.options] == [
        ("metric:widget_revenue", "Widget revenue"), ("metric:refunded_value", "Refunded value"),
    ]
    assert asked.lang == "en"


def test_a_missing_period_offers_relative_periods_in_vietnamese():
    asked = clarification(Need(kind="period"), "vi", compiled_fixture().pack, readable)

    assert asked.question == "Bạn muốn xem khoảng thời gian nào?"
    assert [option.id for option in asked.options] == [
        "period:this_month", "period:last_month", "period:this_quarter", "period:last_quarter", "period:this_year",
        "period:last_year",
    ]
    assert asked.options[3].label == "Quý trước"


def test_other_languages_get_english_text_and_keep_their_language():
    asked = clarification(Need(kind="period"), "fr", compiled_fixture().pack, readable)

    assert asked.question == "Which period should I use?" and asked.options[0].label == "This month"
    assert asked.lang == "fr"


def test_an_ambiguous_column_offers_its_columns():
    need = Need(kind="column", term="item", candidates=["widget_sales.widget_name", "widget_sales.sale_ref"])

    asked = clarification(need, "en", compiled_fixture().pack, readable)

    assert asked.question == 'Which column do you mean by "item"?'
    assert [(option.id, option.label) for option in asked.options] == [
        ("column:widget_sales.widget_name", "widget_name"), ("column:widget_sales.sale_ref", "sale_ref"),
    ]


def test_options_skip_metrics_the_role_may_not_read_and_cap_at_four():
    pack = refunds_clerk(compiled_fixture()).pack
    need = Need(kind="metric", candidates=["widget_revenue", "refunded_value"])

    asked = clarification(need, "en", pack, lambda metric_id: may_read_metric(pack, "refunds_clerk", metric_id))

    assert [option.id for option in asked.options] == ["metric:refunded_value"]


def test_without_readable_candidates_every_readable_metric_is_offered():
    asked = clarification(Need(kind="metric"), "en", compiled_fixture().pack, readable)

    assert [option.id for option in asked.options] == ["metric:widget_revenue", "metric:refunded_value"]


@pytest.mark.parametrize(("role", "metric_id", "expected"), [
    ("viewer", "widget_revenue", True), ("refunds_clerk", "widget_revenue", False), ("refunds_clerk", "refunded_value", True),
])
def test_may_read_metric_follows_the_role_grants(role, metric_id, expected):
    assert may_read_metric(refunds_clerk(compiled_fixture()).pack, role, metric_id) is expected


# gate and graph

def test_the_gate_turns_a_need_into_a_clarification_in_the_question_language():
    parsed = Extraction.model_validate(extraction_reply(language="vi"))

    update = gate({"need": Need(kind="period"), "extraction": parsed}, deps([]))

    assert update["clarification"].question == "Bạn muốn xem khoảng thời gian nào?"


def test_clarify_ends_the_run_before_sql():
    agent = deps([routing_reply(), extraction_reply(rank_term="best")])

    state = run_question("Best widgets in 2024?", agent)

    assert state["clarification"].question == 'Which measure do you mean by "best"?'
    assert state.get("attempts") == [] and agent.runner.calls == []
    assert [call.alias for call in agent.llm.calls] == ["fast", "fast"]


def test_a_question_without_a_period_asks_for_one():
    state = run_question("Top widgets?", deps([routing_reply(), extraction_reply(periods=[], compare=False)]))

    assert [option.id for option in state["clarification"].options][:2] == ["period:this_month", "period:last_month"]
