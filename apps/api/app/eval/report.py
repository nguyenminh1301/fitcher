"""Eval reports and the regression check against a baseline run (DECISIONS §12, §14).

Rates count only the cases a layer scored. A baseline comparison looks at the
cases both runs scored on a layer, so added, removed or newly activated cases
never count as a regression; a layer regresses when its pass count over those
cases drops by more than the tolerance. The pack meets its threshold when the
execution match rate reaches the run's threshold.
"""

from collections.abc import Sequence

from pydantic import BaseModel

from app.eval.runner import EvalRun
from app.eval.scorers import LAYERS, CaseScore, Layer, LayerScore


class LayerTotals(BaseModel):
    passed: int = 0
    failed: int = 0
    not_scored: int = 0

    @property
    def rate(self) -> float | None:
        scored = self.passed + self.failed
        return self.passed / scored if scored else None


def _count(totals: LayerTotals, score: LayerScore) -> None:
    if score.status == "pass":
        totals.passed += 1
    elif score.status == "fail":
        totals.failed += 1
    else:
        totals.not_scored += 1


def layer_totals(cases: Sequence[CaseScore]) -> dict[Layer, LayerTotals]:
    totals = {layer: LayerTotals() for layer in LAYERS}
    for case in cases:
        for layer in LAYERS:
            _count(totals[layer], case.layers[layer])
    return totals


def category_totals(cases: Sequence[CaseScore]) -> dict[str, dict[Layer, LayerTotals]]:
    categories: dict[str, list[CaseScore]] = {}
    for case in cases:
        categories.setdefault(case.category, []).append(case)
    return {category: layer_totals(members) for category, members in sorted(categories.items())}


class LayerDelta(BaseModel):
    common: int
    baseline_passed: int
    current_passed: int

    @property
    def drop(self) -> int:
        return self.baseline_passed - self.current_passed


class BaselineDiff(BaseModel):
    layers: dict[Layer, LayerDelta]
    regressed: list[Layer]


def diff_baseline(baseline: EvalRun, current: EvalRun, tolerance: int = 1) -> BaselineDiff:
    before = {case.case_id: case for case in baseline.cases}
    layers: dict[Layer, LayerDelta] = {}
    for layer in LAYERS:
        pairs = [
            (before[case.case_id].layers[layer].status, case.layers[layer].status)
            for case in current.cases
            if case.case_id in before
            and before[case.case_id].layers[layer].status != "not_scored"
            and case.layers[layer].status != "not_scored"
        ]
        layers[layer] = LayerDelta(
            common=len(pairs),
            baseline_passed=sum(old == "pass" for old, _ in pairs),
            current_passed=sum(new == "pass" for _, new in pairs),
        )
    return BaselineDiff(layers=layers, regressed=[layer for layer in LAYERS if layers[layer].drop > tolerance])


def meets_threshold(run: EvalRun) -> bool:
    rate = layer_totals(run.cases)["execution"].rate
    return rate is not None and rate >= run.threshold


def _cell(text: str) -> str:
    return " ".join(text.replace("|", "\\|").split())


def _percent(rate: float | None) -> str:
    return "-" if rate is None else f"{rate:.0%}"


def _status(score: LayerScore) -> str:
    return "-" if score.status == "not_scored" else score.status


def _reason(case: CaseScore) -> str:
    if case.error:
        return case.error
    failed = next((case.layers[layer].reason for layer in LAYERS if case.layers[layer].status == "fail"), None)
    if failed:
        return failed
    return "" if case.active else case.layers["execution"].reason or ""


def _mean_recall(cases: Sequence[CaseScore]) -> str:
    recalls = [case.layers["retrieval"].recall for case in cases if case.layers["retrieval"].recall is not None]
    return f"{sum(recalls) / len(recalls):.2f}" if recalls else "-"


def render_markdown(run: EvalRun, diff: BaselineDiff | None = None) -> str:
    totals = layer_totals(run.cases)
    execution = totals["execution"]
    met = "met" if meets_threshold(run) else "not met"
    lines = [
        f"# Eval report: {run.pack}",
        "",
        f"Reference date: {run.reference_date.isoformat()}. "
        f"Execution match {_percent(execution.rate)} ({execution.passed}/{execution.passed + execution.failed}), "
        f"threshold {run.threshold:.0%}: {met}.",
        "",
        "## Layers",
        "",
        "| Layer | Passed | Failed | Not scored | Rate | Mean recall |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for layer in LAYERS:
        item = totals[layer]
        recall = _mean_recall(run.cases) if layer == "retrieval" else "-"
        lines.append(f"| {layer} | {item.passed} | {item.failed} | {item.not_scored} | {_percent(item.rate)} | {recall} |")

    lines += ["", "## Categories", "", f"| Category | {' | '.join(LAYERS)} |", f"|{' --- |' * (len(LAYERS) + 1)}"]
    for category, layers in category_totals(run.cases).items():
        cells = [
            f"{item.passed}/{item.passed + item.failed}" if item.passed + item.failed else "-"
            for item in (layers[layer] for layer in LAYERS)
        ]
        lines.append(f"| {category} | {' | '.join(cells)} |")

    if diff is not None:
        lines += [
            "", "## Baseline", "",
            "| Layer | Common cases | Baseline passed | Current passed | Delta | Status |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for layer in LAYERS:
            delta = diff.layers[layer]
            change = f"{-delta.drop:+d}" if delta.drop else "0"
            status = "REGRESSION" if layer in diff.regressed else ""
            lines.append(
                f"| {layer} | {delta.common} | {delta.baseline_passed} | {delta.current_passed} | {change} | {status} |"
            )

    lines += [
        "", "## Cases", "",
        f"| Case | Category | {' | '.join(LAYERS)} | Reason |",
        f"|{' --- |' * (len(LAYERS) + 3)}",
    ]
    for case in run.cases:
        statuses = " | ".join(_status(case.layers[layer]) for layer in LAYERS)
        lines.append(f"| {case.case_id} | {case.category} | {statuses} | {_cell(_reason(case))} |")

    if run.reference_errors:
        lines += ["", "## Reference errors", "", *(f"- {_cell(error)}" for error in run.reference_errors)]
    return "\n".join(lines) + "\n"
