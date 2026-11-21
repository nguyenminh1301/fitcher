"""The console's Evaluation section: eval reports and starting an eval run (DECISIONS §15).

The owner reads the reports and starts a run, which is billable, runs in the background inside the api and
answers 409 while another run of the pack has not finished, or when the pack has
no evaluation set to run (a pack built from a source starts without one).
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.console import Owner
from app.api.runtime import get_compiled_or_none, get_eval_reports, get_eval_runs, unavailable
from app.contracts.evaluation import EvalReportView, EvalRunStarted
from app.eval.cases import EvalSetError, load_eval_set
from app.eval.console import EvalReports, EvalRuns, RunInProgress
from app.packs.compiler import CompiledPack

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin")


Reports = Annotated[EvalReports, Depends(get_eval_reports)]


@router.get("/eval-reports")
def list_reports(_: Owner, reports: Reports) -> list[EvalReportView]:
    try:
        return reports.list()
    except Exception as error:  # noqa: BLE001 - ClickHouse unreachable or a stored report that no longer parses
        logger.error("reading eval reports failed", exc_info=error)
        raise unavailable("the eval reports are unavailable") from None


@router.get("/eval-reports/{report_id}")
def read_report(report_id: str, _: Owner, reports: Reports) -> EvalReportView:
    try:
        report = reports.get(report_id)
    except Exception as error:  # noqa: BLE001 - as above
        logger.error("reading an eval report failed", exc_info=error)
        raise unavailable("the eval reports are unavailable") from None
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="eval report not found")
    return report


@router.post("/eval-runs", status_code=status.HTTP_202_ACCEPTED)
def start_run(
    _: Owner, reports: Reports,
    runs: Annotated[EvalRuns, Depends(get_eval_runs)], compiled: Annotated[CompiledPack | None, Depends(get_compiled_or_none)],
) -> EvalRunStarted:
    # The run itself goes to the background, so a pack it cannot run is refused here rather than failing unseen.
    if compiled is not None:
        try:
            load_eval_set(compiled.pack)
        except EvalSetError as error:
            raise HTTPException(status.HTTP_409_CONFLICT, detail=f"no_eval_set: {error}") from None
    try:
        runs.start(reports.pack)
    except RunInProgress as error:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(error)) from None
    return EvalRunStarted(pack=reports.pack, running=True)
