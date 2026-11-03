"""Score one eval case per layer from the graph's final state (DECISIONS §12).

- intent: the router chose the labelled intent.
- extraction: the resolved periods, ``top_n`` and ``rank_by`` match the labels exactly.
- retrieval: recall of the labelled dataset and columns among the retrieved candidates.
- execution: the answer's result set matches the reference result; for a case
  that expects a denial, a clarifying question or an out-of-scope reply, the
  run ended that way. A denial and an out-of-scope reply score no extraction
  or retrieval.

A case whose branch a later phase builds is not scored on any layer.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.agent.nodes.retrieve import Retrieval
from app.agent.state import AgentState
from app.contracts.result import Result
from app.eval.cases import ranks
from app.eval.compare import Tolerance, compare_results
from app.packs.models import EvalCase, EvalExpected

Layer = Literal["intent", "extraction", "retrieval", "execution"]
LAYERS: tuple[Layer, ...] = ("intent", "extraction", "retrieval", "execution")
Status = Literal["pass", "fail", "not_scored"]


class LayerScore(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Status
    reason: str | None = None
    recall: float | None = None


class CaseScore(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    category: str
    question: str
    active: bool
    layers: dict[Layer, LayerScore]
    error: str | None = None
    seconds: float = 0.0
    # The agent run's trace in agent_logs; empty when the case was not run or the run raised.
    trace_id: str = ""


def _passed_or(reasons: list[str]) -> LayerScore:
    return LayerScore(status="fail", reason="; ".join(reasons)) if reasons else LayerScore(status="pass")


def score_extraction(expected: EvalExpected, state: AgentState) -> LayerScore:
    extraction = state.get("extraction")
    if extraction is None:
        return LayerScore(status="fail", reason="no extraction")
    reasons = []
    wanted = sorted((period.start, period.end) for period in expected.periods)
    got = sorted((period.start.isoformat(), period.end.isoformat()) for period in state.get("periods", []))
    if wanted != got:
        reasons.append(f"periods: expected {wanted}, got {got}")
    if expected.top_n != extraction.top_n:
        reasons.append(f"top_n: expected {expected.top_n}, got {extraction.top_n}")
    spec = state.get("spec")
    rank_by = spec.rank_by if spec is not None else None
    if expected.rank_by != rank_by:
        reasons.append(f"rank_by: expected {expected.rank_by}, got {rank_by}")
    return _passed_or(reasons)


def retrieved_candidates(retrieval: Retrieval) -> tuple[set[str], set[tuple[str, str]]]:
    """Datasets and ``(dataset, column)`` pairs that any retrieved hit points to."""
    hits = [
        *(hit for hits in retrieval.metric_terms.values() for hit in hits),
        *(hit for hits in retrieval.dimension_terms.values() for hit in hits),
        *(hit for hits in retrieval.values.values() for hit in hits),
        *retrieval.examples,
        *retrieval.datasets,
    ]
    datasets: set[str] = set()
    columns: set[tuple[str, str]] = set()
    for hit in hits:
        source, payload = hit.source, hit.source.get("payload", {})
        dataset = source.get("dataset")
        if dataset:
            datasets.add(dataset)
            for key in ("column", "time_column"):
                if payload.get(key):
                    columns.add((dataset, payload[key]))
        for target in payload.get("targets", []):
            if target.get("dataset"):
                datasets.add(target["dataset"])
                if target.get("column"):
                    columns.add((target["dataset"], target["column"]))
        datasets.update(payload.get("datasets", []))
    return datasets, columns


def score_retrieval(expected: EvalExpected, state: AgentState) -> LayerScore:
    if expected.dataset is None and not expected.columns:
        return LayerScore(status="not_scored", reason="no dataset or columns labelled")
    retrieval = state.get("retrieval")
    if retrieval is None:
        return LayerScore(status="fail", reason="retrieval did not run", recall=0.0)
    datasets, columns = retrieved_candidates(retrieval)
    checks = [(expected.dataset, expected.dataset in datasets)] if expected.dataset else []
    checks += [(f"{expected.dataset}.{column}", (expected.dataset, column) in columns) for column in expected.columns]
    recall = sum(found for _, found in checks) / len(checks)
    missing = [label for label, found in checks if not found]
    if missing:
        return LayerScore(status="fail", reason=f"missing: {', '.join(missing)}", recall=recall)
    return LayerScore(status="pass", recall=recall)


def score_execution(
    case: EvalCase, state: AgentState, reference: Result | None, tolerance: Tolerance = Tolerance()
) -> LayerScore:
    if reference is None:
        return LayerScore(status="fail", reason="no reference result")
    result = state.get("result")
    if result is None:
        if state.get("rejection"):
            return LayerScore(status="fail", reason=f"rejected: {state['rejection']}")
        errors = [attempt.error for attempt in state.get("attempts", []) if attempt.error is not None]
        return LayerScore(status="fail", reason=str(errors[-1]) if errors else "no result")
    comparison = compare_results(reference, result, ordered=ranks(case), tolerance=tolerance)
    return LayerScore(status="pass") if comparison.match else LayerScore(status="fail", reason=comparison.reason)


def score_denial(state: AgentState) -> LayerScore:
    if state.get("denial") is not None:
        return LayerScore(status="pass")
    if state.get("result") is not None:
        return LayerScore(status="fail", reason="expected a denial, but the question was answered")
    if state.get("rejection"):
        return LayerScore(status="fail", reason=f"expected a denial, but the question was rejected: {state['rejection']}")
    if state.get("clarification") is not None:
        return LayerScore(status="fail", reason="expected a denial, but the run asked a clarifying question")
    errors = [attempt.error for attempt in state.get("attempts", []) if attempt.error is not None]
    return LayerScore(status="fail", reason=f"expected a denial, got {errors[-1] if errors else 'no decision'}")


def score_intent(expected: EvalExpected, state: AgentState) -> LayerScore:
    got = state.get("intent")
    if got == expected.intent:
        return LayerScore(status="pass")
    return LayerScore(status="fail", reason=f"expected {expected.intent}, got {got or 'no intent'}")


def score_clarification(state: AgentState) -> LayerScore:
    if state.get("clarification") is not None:
        return LayerScore(status="pass")
    if state.get("result") is not None:
        return LayerScore(status="fail", reason="expected a clarifying question, but the question was answered")
    if state.get("rejection"):
        return LayerScore(status="fail", reason=f"expected a clarifying question, but the question was rejected: {state['rejection']}")
    if state.get("denial") is not None:
        return LayerScore(status="fail", reason="expected a clarifying question, but the question was denied")
    return LayerScore(status="fail", reason="expected a clarifying question, got no decision")


def score_reply(state: AgentState) -> LayerScore:
    if state.get("attempts"):
        return LayerScore(status="fail", reason="expected an out-of-scope reply, but SQL was generated")
    if state.get("reply") is not None:
        return LayerScore(status="pass")
    return LayerScore(status="fail", reason="expected an out-of-scope reply, got none")


def score_case(case: EvalCase, state: AgentState, reference: Result | None, *, active: bool) -> CaseScore:
    expected = case.expected
    decision_only = LayerScore(status="not_scored", reason="this case scores the decision only")
    if not active:
        skipped = LayerScore(status="not_scored", reason=f"not yet scored: active from phase {case.active_from_phase}")
        layers = dict.fromkeys(LAYERS, skipped)
    elif expected.outcome == "deny":
        layers = {"intent": score_intent(expected, state), "extraction": decision_only, "retrieval": decision_only,
                  "execution": score_denial(state)}
    elif expected.intent == "out_of_scope":
        layers = {"intent": score_intent(expected, state), "extraction": decision_only, "retrieval": decision_only,
                  "execution": score_reply(state)}
    else:
        execution = score_clarification(state) if expected.outcome == "clarify" else score_execution(case, state, reference)
        layers = {
            "intent": score_intent(expected, state),
            "extraction": score_extraction(expected, state),
            "retrieval": score_retrieval(expected, state),
            "execution": execution,
        }
    return CaseScore(case_id=case.id, category=case.category, question=case.question, active=active, layers=layers)
