"""Run a pack's eval set through the graph, one case at a time (DECISIONS §12).

Each active case first obtains its reference result, from ``expected_sql``
run on the read-only ClickHouse user or from inline ``expected_rows``, then
asks its question with its own trace id and a time limit; a case with a
``previous_question`` asks that first, and its question follows it up in the
same conversation within the same time limit. Every case runs as its ``role``: retrieval, the guard and, through ``runner_for``, the ClickHouse
user are that role's, and so is its reference query. A failing reference
query, an exception or a timeout fails that case and the run continues;
inactive cases are reported without running.
"""

from collections.abc import Callable
from dataclasses import replace
from datetime import date
import threading
import time
from typing import TypeVar

from pydantic import BaseModel

from app.agent.graph import run_question
from app.agent.nodes.shape_result import describe_column, to_result
from app.agent.state import AgentDeps, AgentState, QueryRunner
from app.contracts.result import Result
from app.conversation.store import Turn
from app.data.clickhouse import QueryError
from app.eval.cases import EvalSet, is_active
from app.eval.scorers import CaseScore, LayerScore, score_case
from app.packs.models import EvalCase

T = TypeVar("T")


class CaseTimeout(Exception):
    """A case did not finish within its time limit."""


class ReferenceQueryError(Exception):
    """A case's reference result could not be obtained."""


class PreviousQuestionError(Exception):
    """The question a follow-up case follows could not be asked."""


def call_with_timeout(fn: Callable[[], T], seconds: float) -> T:
    """Return ``fn()`` or raise its exception, or raise ``CaseTimeout`` after ``seconds``.

    The call runs in a daemon thread that is abandoned on timeout; the
    ClickHouse profile's execution limit bounds any query it leaves running.
    """
    outcome: dict[str, object] = {}

    def target() -> None:
        try:
            outcome["value"] = fn()
        except BaseException as error:  # noqa: BLE001 - re-raised in the caller's thread
            outcome["error"] = error

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(seconds)
    if thread.is_alive():
        raise CaseTimeout(f"timed out after {seconds:g}s")
    if "error" in outcome:
        raise outcome["error"]
    return outcome["value"]


def _clickhouse_type(values: list[object]) -> str:
    value = next((value for value in values if value is not None), None)
    if isinstance(value, bool):
        return "Bool"
    if isinstance(value, (int, float)):
        return "Float64"
    return "String"


def reference_result(case: EvalCase, deps: AgentDeps) -> Result:
    pack, dataset = deps.compiled.pack, case.expected.dataset or ""
    if case.expected_rows is not None:
        names = list(case.expected_rows[0])
        rows = [[row[name] for name in names] for row in case.expected_rows]
        columns = [
            describe_column(name, _clickhouse_type([row[index] for row in rows]), pack, dataset)
            for index, name in enumerate(names)
        ]
        return Result(columns=columns, rows=rows, row_count=len(rows))
    try:
        output = deps.runner.run(case.expected_sql, trace_id=f"eval-reference-{case.id}")
    except QueryError as error:
        raise ReferenceQueryError(f"{case.id}: {error}") from error
    return to_result(output, pack, dataset)


class EvalRun(BaseModel):
    pack: str
    reference_date: date
    threshold: float
    cases: list[CaseScore]
    reference_errors: list[str] = []


def _failed(case: EvalCase, reference: Result | None, error: str) -> CaseScore:
    """Score a case whose graph run raised: every layer that would be scored fails with the error."""
    score = score_case(case, {}, reference, active=True)
    layers = {
        name: LayerScore(status="fail", reason=error, recall=layer.recall) if layer.status == "fail" else layer
        for name, layer in score.layers.items()
    }
    return score.model_copy(update={"layers": layers, "error": error})


def _answer(state: AgentState) -> str:
    clarification = state.get("clarification")
    return state.get("summary") or state.get("reply") or (clarification.question if clarification else "")


def ask_in_conversation(case: EvalCase, deps: AgentDeps) -> AgentState:
    """Ask the case's question, after its previous question when it has one."""
    if case.previous_question is None:
        return run_question(case.question, deps)
    try:
        previous = run_question(case.previous_question, deps)
    except Exception as error:  # noqa: BLE001 - reported as the case's error
        raise PreviousQuestionError(f"previous question: {type(error).__name__}: {error}") from error
    turn = Turn(
        turn=1, revision=1, question=case.previous_question, answer=_answer(previous), query_spec=previous.get("spec"),
        result=previous.get("result"), trace_id=previous["trace_id"],
    )
    return run_question(case.question, replace(deps, history=(turn,)))


def _run_case(case: EvalCase, deps: AgentDeps, timeout: float, reference_errors: list[str]) -> CaseScore:
    reference, reference_error = None, None
    try:
        # A case that expects a denial has no reference result to compare.
        if case.expected.outcome == "answer":
            reference = reference_result(case, deps)
    except ReferenceQueryError as error:
        reference_error = str(error).removeprefix(f"{case.id}: ")
        reference_errors.append(str(error))
    try:
        state = call_with_timeout(lambda: ask_in_conversation(case, deps), timeout)
    except (CaseTimeout, PreviousQuestionError) as error:
        return _failed(case, reference, str(error))
    except Exception as error:  # noqa: BLE001 - one failing case never aborts the run
        return _failed(case, reference, f"{type(error).__name__}: {error}")
    score = score_case(case, state, reference, active=True).model_copy(update={"trace_id": state["trace_id"]})
    if reference_error is not None:
        layers = {**score.layers, "execution": LayerScore(status="fail", reason=f"reference: {reference_error}")}
        score = score.model_copy(update={"layers": layers})
    return score


def run_eval(
    pack: str,
    eval_set: EvalSet,
    deps: AgentDeps,
    *,
    timeout: float,
    threshold: float,
    clock: Callable[[], float] = time.monotonic,
    runner_for: Callable[[str], QueryRunner] | None = None,
) -> EvalRun:
    """Run ``eval_set``; ``runner_for(role)`` gives each case's query runner, ``deps.runner`` when None."""
    scores: list[CaseScore] = []
    reference_errors: list[str] = []
    for case in eval_set.cases:
        if not is_active(case):
            scores.append(score_case(case, {}, None, active=False))
            continue
        started = clock()
        runner = runner_for(case.role) if runner_for is not None else deps.runner
        score = _run_case(case, replace(deps, role=case.role, runner=runner), timeout, reference_errors)
        scores.append(score.model_copy(update={"seconds": round(clock() - started, 3)}))
    return EvalRun(
        pack=pack, reference_date=eval_set.reference_date, threshold=threshold, cases=scores,
        reference_errors=reference_errors,
    )
