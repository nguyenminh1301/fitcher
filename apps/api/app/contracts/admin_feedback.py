"""Answer feedback as the console's Feedback section shows it (DECISIONS §15)."""

from datetime import datetime
from typing import Literal

from app.contracts.query_spec import ContractModel


class FeedbackRow(ContractModel):
    trace_id: str
    ts: datetime
    user_id: str
    rating: Literal["like", "dislike"]
    question: str
    note: str | None = None
    run_status: str
    # The latest state of an example proposed from this run, if any.
    proposal: Literal["proposed", "approved", "dismissed"] | None = None


class ProposalResult(ContractModel):
    """The proposal stored from one run, or why the run cannot become one."""

    proposed: bool
    proposal_id: str | None = None
    question: str | None = None
    reason: str | None = None
