"""Eval reports and eval runs for the console's Evaluation section (DECISIONS §15).

``EvalReports`` reads ``agent_logs.eval_reports`` of the active pack as the
trace reader and turns each stored ``EvalRun`` into the page's view.
``EvalRuns`` starts a run of the pack's eval set in a background thread inside
the api, one per pack at a time; the run itself is ``jobs.eval``, so it uses
the same runner, report and storage as the command line. A run is billable.
"""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
import threading
from typing import Protocol

from app.contracts.evaluation import EvalLayer, EvalReportView, FailedCase
from app.eval.report import category_totals, layer_totals, meets_threshold
from app.eval.runner import EvalRun
from app.eval.scorers import LAYERS

REPORTS = 50


class Query(Protocol):
    def __call__(self, sql: str, parameters: dict) -> Sequence[Sequence]: ...


class RunInProgress(Exception):
    """An eval run of this pack has not finished yet."""


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def report_view(report_id: str, ts: datetime, run: EvalRun, regressed: bool | None) -> EvalReportView:
    layers = {layer: EvalLayer(passed=t.passed, failed=t.failed, not_scored=t.not_scored)
              for layer, t in layer_totals(run.cases).items()}
    categories = {
        category: f"{totals['execution'].passed}/{totals['execution'].passed + totals['execution'].failed}"
        for category, totals in sorted(category_totals(run.cases).items())
    }
    failed = []
    for case in run.cases:
        failing = next((layer for layer in LAYERS if case.layers[layer].status == "fail"), None)
        if case.error or failing:
            failed.append(FailedCase(case_id=case.case_id, category=case.category,
                                     reason=case.error or case.layers[failing].reason or failing))
    return EvalReportView(id=report_id, ts=_aware(ts), passed=meets_threshold(run), threshold=run.threshold,
                          layers=layers, categories=categories, failed_cases=failed, regressed=regressed)


class EvalReports:
    def __init__(self, query: Query, pack: str):
        self.query = query
        self.pack = pack

    def list(self) -> list[EvalReportView]:
        rows = self.query(
            "SELECT report_id, ts, report, regressed FROM agent_logs.eval_reports WHERE pack = {pack:String} "
            "ORDER BY ts DESC LIMIT {limit:UInt32}", {"pack": self.pack, "limit": REPORTS},
        )
        return [report_view(report_id, ts, EvalRun.model_validate_json(report), regressed)
                for report_id, ts, report, regressed in rows]

    def get(self, report_id: str) -> EvalReportView | None:
        rows = self.query(
            "SELECT report_id, ts, report, regressed FROM agent_logs.eval_reports "
            "WHERE pack = {pack:String} AND report_id = {id:String} LIMIT 1", {"pack": self.pack, "id": report_id},
        )
        if not rows:
            return None
        report_id, ts, report, regressed = rows[0]
        return report_view(report_id, ts, EvalRun.model_validate_json(report), regressed)


class EvalRuns:
    """One background eval run per pack; ``execute(pack)`` runs it and stores its report."""

    def __init__(self, execute: Callable[[str], int], start_thread: Callable[[Callable[[], None]], None] | None = None):
        self._execute = execute
        self._start_thread = start_thread or (lambda target: threading.Thread(target=target, daemon=True).start())
        self._running: set[str] = set()
        self._lock = threading.Lock()

    def running(self, pack: str) -> bool:
        with self._lock:
            return pack in self._running

    def start(self, pack: str) -> None:
        with self._lock:
            if pack in self._running:
                raise RunInProgress(f"an eval run of {pack} is still running")
            self._running.add(pack)

        def target() -> None:
            try:
                self._execute(pack)
            finally:
                with self._lock:
                    self._running.discard(pack)

        self._start_thread(target)
