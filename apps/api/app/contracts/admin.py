"""What the console's admin sections read from ``agent_logs`` (DECISIONS §10 and §15)."""

from datetime import datetime
from typing import Literal

from app.contracts.query_spec import ContractModel


class RunRow(ContractModel):
    trace_id: str
    ts: datetime
    user_id: str
    # The pack role the run used, from its access decision; empty when it stopped before one.
    role: str
    question: str
    intent: str
    status: str
    latency_ms: int
    cost_usd: float
    error: str = ""


class TraceItem(ContractModel):
    """One step of a run, in time order: a graph node, an LLM call, a SQL attempt or an access decision."""

    name: str
    kind: Literal["node", "llm", "sql", "access"]
    status: Literal["ok", "err", "deny"]
    ms: int | None = None
    meta: list[str] = []
    sql: str | None = None
    error: str | None = None


class RunTrace(ContractModel):
    run: RunRow
    items: list[TraceItem]


class AuditRow(ContractModel):
    ts: datetime
    trace_id: str
    user_id: str
    role: str
    decision: Literal["ALLOW", "DENY"]
    dataset: str
    blocked_tables: list[str]
    reason: str


class ScreeningRow(ContractModel):
    ts: datetime
    trace_id: str
    user_id: str
    source: str
    verdict: str
    mode: str
    score: float | None
    rule_hits: list[str]


class CostRow(ContractModel):
    """Estimated LLM cost of one day, provider, model and tier, from the LiteLLM SDK's price table."""

    day: str
    alias: str
    model: str
    tier: str
    provider: str
    calls: int
    cost_usd: float


class AdminConversation(ContractModel):
    conversation_id: str
    user_id: str
    title: str
    # Deleted by its owner: hidden from them, still readable here until the 90-day TTL.
    deleted: bool
    updated_at: datetime


class AdminMessage(ContractModel):
    ts: datetime
    role: str
    content: str
    trace_id: str
    turn: int
    revision: int


class AdminConversationThread(ContractModel):
    conversation: AdminConversation
    messages: list[AdminMessage]
