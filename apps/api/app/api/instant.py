"""``/pack/instant``: build a pack from a connected source's chosen tables and follow the job (DECISIONS §11 step 0).

Only an ``admin`` reaches these endpoints (the owner in individual mode). ``POST /pack/instant/estimate`` shows
the draft's prompt size and whether a model can draft before anything runs; ``POST /pack/instant`` starts the job
only with ``confirm_billable`` set, because the draft is a paid model call; ``GET /pack/instant/{job}`` reports
each step and, at the end, the result or the step that failed.
"""

from dataclasses import asdict
import logging
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.console import require_admin
from app.api.runtime import get_admin_action_log, get_instant_pipeline
from app.auth.principal import Principal
from app.contracts.instant import InstantEstimate, InstantEstimateRequest, InstantJobReply, InstantJobView, InstantRequest
from app.observability.events import AdminActionRecord, utc_now
from app.onboarding.instant import InstantJob, InstantPipeline, InstantRefused

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/pack/instant")
Admin = Annotated[Principal, Depends(require_admin)]
Pipeline = Annotated[InstantPipeline, Depends(get_instant_pipeline)]


class ActionLog(Protocol):
    def record_action(self, record: AdminActionRecord) -> None: ...


Log = Annotated[ActionLog, Depends(get_admin_action_log)]


def _reply(job: InstantJob) -> InstantJobReply:
    fields = asdict(job)
    fields.pop("started_by")
    return InstantJobReply(job=InstantJobView.model_validate(fields))


def _refused(error: InstantRefused) -> HTTPException:
    return HTTPException(error.status, detail=str(error))


@router.post("/estimate", response_model=InstantEstimate)
def estimate(body: InstantEstimateRequest, admin: Admin, pipeline: Pipeline) -> InstantEstimate:
    try:
        return InstantEstimate(**pipeline.estimate(body.source_id, body.tables))
    except InstantRefused as error:
        raise _refused(error) from None


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=InstantJobReply)
def start(body: InstantRequest, admin: Admin, pipeline: Pipeline, log: Log) -> InstantJobReply:
    try:
        job = pipeline.start(body.source_id, body.tables, confirm_billable=body.confirm_billable, started_by=admin.user_id)
    except InstantRefused as error:
        raise _refused(error) from None
    try:
        log.record_action(AdminActionRecord(ts=utc_now(), actor=admin.user_id, action="pack.instant", target=body.source_id,
                                            old_value="", new_value=",".join(body.tables)))
    except Exception:  # noqa: BLE001 - the job already started
        logger.exception("the instant pack of %s was not recorded", body.source_id)
    return _reply(job)


@router.get("/{job_id}", response_model=InstantJobReply)
def job(job_id: str, admin: Admin, pipeline: Pipeline) -> InstantJobReply:
    found = pipeline.job(job_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="no such instant pack job")
    return _reply(found)
