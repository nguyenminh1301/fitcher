"""Write one access decision of a run to ``agent_logs.audit`` (DECISIONS §9)."""

from typing import Literal

from app.agent.state import AgentDeps, AgentState
from app.observability.events import AuditRecord, utc_now


def audit(
    state: AgentState, deps: AgentDeps, decision: Literal["ALLOW", "DENY"], dataset: str, blocked: list[str], reason: str
) -> None:
    """Queue the decision for the run's trace; without a log writer (unit tests) nothing is written."""
    if deps.logs is None:
        return
    deps.logs.enqueue(AuditRecord(
        trace_id=state["trace_id"], ts=utc_now(), user_id=deps.user_id, role=deps.role, decision=decision,
        dataset=dataset, blocked_tables=blocked, reason=reason,
    ))
