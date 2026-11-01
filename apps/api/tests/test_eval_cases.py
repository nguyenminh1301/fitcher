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


def test_only_filters_and_unknown_id_is_an_error():
    pack = _pack([_case("first"), _case("second")])

    assert [case.id for case in load_eval_set(pack, only=["second"]).cases] == ["second"]
    with pytest.raises(EvalSetError, match="nope"):
        load_eval_set(pack, only=["second", "nope"])


def test_active_answer_case_needs_sql_or_rows():
    with pytest.raises(EvalSetError, match="no_reference"):
        load_eval_set(_pack([_case("no_reference", expected_sql=None)]))


def test_active_case_must_be_an_answered_data_query():
    clarify = EvalExpected(intent="data_query", outcome="clarify")

    with pytest.raises(EvalSetError, match="unlabelled_clarify"):
        load_eval_set(_pack([_case("unlabelled_clarify", expected=clarify, expected_sql=None)]))


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
