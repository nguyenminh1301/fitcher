"""The console's Evaluation section: eval reports and starting an eval run (DECISIONS §15).

Reports are read by a ``pack_reviewer`` or an ``admin``; only an ``admin``
starts a run, which is billable, runs in the background inside the api and
answers 409 while another run of the pack has not finished.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.auth import current_principal
from app.api.console import ADMIN, PACK_REVIEWER, require_admin
from app.api.runtime import get_eval_reports, get_eval_runs, unavailable
from app.auth.jwt import Principal
from app.contracts.evaluation import EvalReportView, EvalRunStarted
from app.eval.console import EvalReports, EvalRuns, RunInProgress

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin")


def require_reviewer_or_admin(principal: Annotated[Principal, Depends(current_principal)]) -> Principal:
    if not {PACK_REVIEWER, ADMIN} & set(principal.roles):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="the Evaluation section needs pack_reviewer or admin")
    return principal


Reader = Annotated[Principal, Depends(require_reviewer_or_admin)]
Reports = Annotated[EvalReports, Depends(get_eval_reports)]


@router.get("/eval-reports")
def list_reports(_: Reader, reports: Reports) -> list[EvalReportView]:
    try:
        return reports.list()
    except Exception as error:  # noqa: BLE001 - ClickHouse unreachable or a stored report that no longer parses
        logger.error("reading eval reports failed", exc_info=error)
        raise unavailable("the eval reports are unavailable") from None


@router.get("/eval-reports/{report_id}")
def read_report(report_id: str, _: Reader, reports: Reports) -> EvalReportView:
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
    _: Annotated[Principal, Depends(require_admin)], reports: Reports,
    runs: Annotated[EvalRuns, Depends(get_eval_runs)],
) -> EvalRunStarted:
    try:
        runs.start(reports.pack)
    except RunInProgress as error:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(error)) from None
    return EvalRunStarted(pack=reports.pack, running=True)
