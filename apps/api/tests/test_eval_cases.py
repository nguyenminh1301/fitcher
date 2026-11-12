"""Loading a pack's eval set: approved cases, the reference date and the active-case rules."""

from datetime import date

from conftest import FIXTURE_PACK, SCHEMA_DIR
import pytest

from app.eval.cases import ENGINE_PHASE, EvalSetError, is_active, load_eval_set, ranks
from app.packs.loader import load_pack
from app.packs.models import EvalCase, EvalExpected, Pack


def _pack(cases: list[EvalCase] | None = None, reference_date: str | None = "2026-01-15") -> Pack:
    pack = load_pack(FIXTURE_PACK, schema_dir=SCHEMA_DIR)
    eval_file = pack.eval.model_copy(update={
        "reference_date": reference_date,
        "cases": pack.eval.cases if cases is None else cases,
    })
    return pack.model_copy(update={"eval": eval_file})


def _case(case_id: str, **updates) -> EvalCase:
    base = load_pack(FIXTURE_PACK, schema_dir=SCHEMA_DIR).eval.cases[0]
    return base.model_copy(update={"id": case_id, **updates})


def test_loads_approved_cases_with_reference_date():
    pack = _pack([_case("kept"), _case("drafted", status="draft")])

    eval_set = load_eval_set(pack)

    assert eval_set.reference_date == date(2026, 1, 15)
    assert [case.id for case in eval_set.cases] == ["kept"]


def test_missing_reference_date_is_an_error():
    with pytest.raises(EvalSetError, match="reference_date"):
        load_eval_set(_pack(reference_date=None))


def test_calendar_invalid_reference_date_is_an_eval_set_error():
    with pytest.raises(EvalSetError, match="2026-13-45"):
        load_eval_set(_pack(reference_date="2026-13-45"))


def test_only_filters_and_unknown_id_is_an_error():
    pack = _pack([_case("first"), _case("second")])

    assert [case.id for case in load_eval_set(pack, only=["second"]).cases] == ["second"]
    with pytest.raises(EvalSetError, match="nope"):
        load_eval_set(pack, only=["second", "nope"])


def test_active_answer_case_needs_sql_or_rows():
    with pytest.raises(EvalSetError, match="no_reference"):
        load_eval_set(_pack([_case("no_reference", expected_sql=None)]))


def test_active_case_must_be_a_branch_the_engine_scores():
    expected = EvalExpected(intent="metadata_qa", outcome="answer")

    with pytest.raises(EvalSetError, match="not_built_yet"):
        load_eval_set(_pack([_case("not_built_yet", expected=expected, expected_sql=None)]))


@pytest.mark.parametrize(("intent", "outcome"), [("data_query", "clarify"), ("out_of_scope", "answer")])
def test_active_clarify_and_out_of_scope_cases_need_no_reference(intent, outcome):
    case = _case("decision", expected=EvalExpected(intent=intent, outcome=outcome), expected_sql=None)

    assert [item.id for item in load_eval_set(_pack([case])).cases] == ["decision"]


def test_a_follow_up_case_needs_its_previous_question():
    with pytest.raises(EvalSetError, match="previous_question"):
        load_eval_set(_pack([_case("orphan", category="follow_up")]))

    asked = _case("asked", category="follow_up", previous_question="Top 10 widgets in Q1 2024 vs Q1 2025")
    assert [item.id for item in load_eval_set(_pack([asked])).cases] == ["asked"]


def test_inactive_case_needs_no_reference():
    clarify = EvalExpected(intent="data_query", outcome="clarify")
    case = _case("later", expected=clarify, expected_sql=None, active_from_phase=ENGINE_PHASE + 4)

    assert [item.id for item in load_eval_set(_pack([case])).cases] == ["later"]


def test_is_active_respects_phase():
    later = _case("later", active_from_phase=6)

    assert is_active(_case("now")) is True
    assert is_active(later, phase=4) is False
    assert is_active(later, phase=6) is True


def test_ranks_for_top_n_and_monthly_trend():
    plain = EvalExpected(intent="data_query", outcome="answer")

    assert ranks(_case("top", expected=plain.model_copy(update={"top_n": 5}))) is True
    assert ranks(_case("trend", category="monthly_trend", expected=plain)) is True
    assert ranks(_case("filter", category="string_filter", expected=plain)) is False


def test_engine_has_reached_the_conversation_branches():
    assert ENGINE_PHASE >= 8


def test_active_deny_case_needs_no_reference():
    deny = EvalExpected(intent="data_query", outcome="deny", metrics=["widget_revenue"], dataset="widget_sales")
    case = _case("blocked", expected=deny, expected_sql=None, active_from_phase=6)

    assert [item.id for item in load_eval_set(_pack([case])).cases] == ["blocked"]


def test_a_chart_edit_case_needs_the_question_it_redraws():
    expected = EvalExpected(intent="chart_edit", outcome="answer")

    with pytest.raises(EvalSetError, match="previous_question"):
        load_eval_set(_pack([_case("orphan", category="chart_edit", expected=expected, expected_sql=None)]))

    redraw = _case("redraw", category="chart_edit", expected=expected, expected_sql=None, previous_question="Top widgets in 2024")
    assert [item.id for item in load_eval_set(_pack([redraw])).cases] == ["redraw"]
