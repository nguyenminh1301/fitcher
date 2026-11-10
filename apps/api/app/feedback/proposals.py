"""Turn disliked or failed data questions into example proposals for review (DECISIONS §11 step 8).

A run is eligible when it is a ``data_query`` that produced a QuerySpec and
SQL and was either disliked or failed after its repairs; clarified, denied,
rejected and blocked runs are not. Every user-derived value is redacted
before storage (``app.feedback.redaction``), proposals never hold result rows
and expire with the 90-day log TTL. A question already proposed for the pack
(compared case-, space- and punctuation-insensitively after redaction) is
skipped. Nothing here calls an LLM.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
import re
from typing import Protocol
import uuid

from app.feedback.redaction import redact, redact_spec, redact_sql

DISLIKE_CONFIDENCE = 0.5
FAILED_CONFIDENCE = 0.3
_NOT_WORD = re.compile(r"[^\w\s]")


@dataclass(frozen=True)
class RunFacts:
    trace_id: str
    pack: str
    question: str
    status: str
    intent: str
    error: str
    spec: dict | None
    sql: str
    rating: str | None
    note: str = ""


@dataclass(frozen=True)
class Proposal:
    proposal_id: str
    pack: str
    ts: datetime
    trace_id: str
    question: str
    sql: str
    source: str
    status: str
    spec: str
    error: str
    note: str
    confidence: float


@dataclass
class ProposeSummary:
    added: list[str] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)


class ProposalStore(Protocol):
    def candidates(self, pack: str, since: datetime) -> Iterable[RunFacts]: ...

    def known_questions(self, pack: str) -> set[str]: ...

    def save(self, proposal: Proposal) -> None: ...


def normalize(question: str) -> str:
    return " ".join(_NOT_WORD.sub(" ", question.lower()).split())


def ineligible_reason(run: RunFacts) -> str | None:
    """Why ``run`` cannot become a proposal, or None when it can."""
    if run.intent != "data_query":
        return "not a data question"
    if run.status in ("clarified", "denied", "rejected", "blocked", "cancelled"):
        return f"the run was {run.status}"
    if run.status != "failed" and run.rating != "dislike":
        return "the run was neither disliked nor failed"
    if not run.spec:
        return "the run produced no QuerySpec"
    if not run.sql:
        return "the run produced no SQL"
    return None


def build_proposal(
    run: RunFacts, *, clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    new_id: Callable[[], str] = lambda: uuid.uuid4().hex,
) -> Proposal:
    failed = run.status == "failed"
    return Proposal(
        proposal_id=new_id(), pack=run.pack, ts=clock(), trace_id=run.trace_id, question=redact(run.question),
        sql=redact_sql(run.sql), source="failed" if failed else "dislike", status="proposed",
        spec=json.dumps(redact_spec(run.spec or {}), ensure_ascii=False), error=redact(run.error) if failed else "",
        note=redact(run.note), confidence=FAILED_CONFIDENCE if failed else DISLIKE_CONFIDENCE,
    )


def propose(
    store: ProposalStore, pack: str, *, since: datetime, clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ProposeSummary:
    """Store a proposal for every eligible run since ``since`` whose question is new for the pack."""
    summary = ProposeSummary()
    known = set(store.known_questions(pack))
    for run in store.candidates(pack, since):
        reason = ineligible_reason(run)
        if reason:
            summary.skipped[run.trace_id] = reason
            continue
        proposal = build_proposal(run, clock=clock)
        key = normalize(proposal.question)
        if key in known:
            summary.skipped[run.trace_id] = "the question was already proposed"
            continue
        store.save(proposal)
        known.add(key)
        summary.added.append(run.trace_id)
    return summary
