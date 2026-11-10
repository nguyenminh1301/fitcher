"""The console's Feedback section: likes and dislikes, and proposing an example from one run (DECISIONS §15).

Only a ``pack_reviewer`` reaches these endpoints. Proposing runs the same code
as ``jobs.propose_examples`` for one run: the answer is the stored proposal,
or ``proposed: false`` with the reason the run is not eligible.
"""

from datetime import datetime
import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.console import require_reviewer
from app.api.runtime import get_compiled_or_none, get_proposal_store, pack_identity, unavailable
from app.auth.jwt import Principal
from app.contracts.admin_feedback import FeedbackRow, ProposalResult
from app.feedback.proposals import build_proposal, ineligible_reason, normalize
from app.feedback.store import ClickHouseProposalStore
from app.packs.compiler import CompiledPack

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/feedback")
Reviewer = Annotated[Principal, Depends(require_reviewer)]
Store = Annotated[ClickHouseProposalStore, Depends(get_proposal_store)]
Compiled = Annotated[CompiledPack | None, Depends(get_compiled_or_none)]


@router.get("")
def list_feedback(
    _: Reviewer, store: Store, compiled: Compiled, rating: Literal["like", "dislike"] | None = None,
    start: Annotated[datetime | None, Query(alias="from")] = None, end: Annotated[datetime | None, Query(alias="to")] = None,
) -> list[FeedbackRow]:
    try:
        return store.feedback(pack_identity(compiled).name, rating, start, end)
    except Exception as error:  # noqa: BLE001 - ClickHouse unreachable or refused the reader
        logger.error("the feedback read failed", exc_info=error)
        raise unavailable("the feedback store is unavailable") from None


@router.post("/{trace_id}/proposal")
def propose_from_run(trace_id: str, _: Reviewer, store: Store, compiled: Compiled) -> ProposalResult:
    pack = pack_identity(compiled).name
    try:
        run = store.run(pack, trace_id)
        if run is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="run not found")
        reason = ineligible_reason(run)
        if reason:
            return ProposalResult(proposed=False, reason=reason)
        proposal = build_proposal(run)
        if normalize(proposal.question) in store.known_questions(pack):
            return ProposalResult(proposed=False, reason="the question was already proposed")
        store.save(proposal)
    except HTTPException:
        raise
    except Exception as error:  # noqa: BLE001 - ClickHouse unreachable or refused the reader or writer
        logger.error("proposing an example failed", exc_info=error)
        raise unavailable("the feedback store is unavailable") from None
    return ProposalResult(proposed=True, proposal_id=proposal.proposal_id, question=proposal.question)
