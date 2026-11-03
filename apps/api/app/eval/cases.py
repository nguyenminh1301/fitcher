"""Load a pack's eval set and decide which cases are scored.

Only approved cases run. A case whose branch a later delivery phase builds
carries ``active_from_phase`` and is reported as not yet scored. An active
case is a ``data_query`` or an ``out_of_scope`` question: a data question that
expects an answer needs a reference result, either ``expected_sql`` or
``expected_rows``; one that expects a clarifying question or a denial, and an
out-of-scope question, need none, and so does a chart edit. A ``follow_up``
or ``chart_edit`` case names the ``previous_question`` it follows.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from app.packs.models import EvalCase, Pack

# The delivery phase the engine has reached; later phases raise it when they
# build the branches their cases need.
ENGINE_PHASE = 8
FOLLOWS_A_QUESTION = ("follow_up", "chart_edit")


class EvalSetError(ValueError):
    """The eval set cannot be run as labelled."""


@dataclass(frozen=True)
class EvalSet:
    reference_date: date
    cases: list[EvalCase]


def is_active(case: EvalCase, phase: int = ENGINE_PHASE) -> bool:
    return case.active_from_phase is None or case.active_from_phase <= phase


def ranks(case: EvalCase) -> bool:
    """Whether row order is part of the expected answer."""
    return case.expected.top_n is not None or case.category == "monthly_trend"


def _check_active(case: EvalCase) -> None:
    expected = case.expected
    if case.category in FOLLOWS_A_QUESTION and case.previous_question is None:
        raise EvalSetError(f"case {case.id} is a {case.category} case and needs previous_question")
    decisions = {("data_query", "deny"), ("data_query", "clarify"), ("out_of_scope", "answer"), ("chart_edit", "answer")}
    if (expected.intent, expected.outcome) in decisions:
        return
    if expected.intent != "data_query" or expected.outcome != "answer":
        raise EvalSetError(
            f"case {case.id} expects {expected.intent}/{expected.outcome}, which this engine cannot answer yet; "
            "set active_from_phase to the phase that builds it"
        )
    if case.expected_sql is None and case.expected_rows is None:
        raise EvalSetError(f"case {case.id} needs expected_sql or expected_rows")


def load_eval_set(pack: Pack, only: Sequence[str] | None = None) -> EvalSet:
    if pack.eval.reference_date is None:
        raise EvalSetError(f"eval.yaml of pack {pack.name} must set reference_date")
    cases = [case for case in pack.eval.cases if case.status == "approved"]
    if only is not None:
        known = {case.id for case in cases}
        unknown = [case_id for case_id in only if case_id not in known]
        if unknown:
            raise EvalSetError(f"no approved eval case with id {', '.join(unknown)}")
        cases = [case for case in cases if case.id in set(only)]
    for case in cases:
        if is_active(case):
            _check_active(case)
    try:
        reference_date = date.fromisoformat(pack.eval.reference_date)
    except ValueError as error:
        raise EvalSetError(
            f"eval.yaml of pack {pack.name} has an invalid reference_date {pack.eval.reference_date}"
        ) from error
    return EvalSet(reference_date=reference_date, cases=cases)
