"""Typed rows of the ``agent_logs`` tables the api writes.

Field names and order equal the table columns in
``infra/clickhouse/initdb/010-agent-logs.sql``; a test compares them. The
LiteLLM callback writes ``llm_calls`` itself, and later phases add records for
the tables they start writing.
"""

from datetime import datetime, UTC
from typing import ClassVar

from pydantic import BaseModel, ConfigDict


def utc_now() -> datetime:
    return datetime.now(UTC)


class LogRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    TABLE: ClassVar[str]


class RunRecord(LogRecord):
    """One state of a run; the row with the latest ``updated_at`` wins."""

    TABLE: ClassVar[str] = "runs"

    trace_id: str
    ts: datetime
    updated_at: datetime
    user_id: str
    pack: str
    question: str
    intent: str
    # running, succeeded, failed, rejected, denied or error
    status: str
    latency_ms: int
    error: str
    # True only when every record the api wrote for the run reached ClickHouse.
    log_complete: bool
    lost_records: int
    # LLM gateway calls the api sent; the trace query compares them with llm_calls rows.
    llm_calls: int


class EventRecord(LogRecord):
    TABLE: ClassVar[str] = "events"

    trace_id: str
    ts: datetime
    ended_at: datetime
    node: str
    # ok or error
    status: str
    duration_ms: int
    payload: str
    payload_truncated: bool


class SqlRunRecord(LogRecord):
    TABLE: ClassVar[str] = "sql_runs"

    trace_id: str
    ts: datetime
    attempt: int
    sql: str
    query_id: str
    rows: int
    error: str


class AuditRecord(LogRecord):
    """One access decision: the gate's or guard's ALLOW of a SQL attempt, or a DENY from any layer."""

    TABLE: ClassVar[str] = "audit"

    trace_id: str
    ts: datetime
    user_id: str
    role: str
    # ALLOW or DENY
    decision: str
    dataset: str
    blocked_tables: list[str]
    reason: str


class EvalReportRecord(LogRecord):
    TABLE: ClassVar[str] = "eval_reports"

    pack: str
    ts: datetime
    report_id: str
    execution_rate: float
    passed: bool
    report: str


class ChatMessageRecord(LogRecord):
    """One question (``user``) or answer (``assistant``) of a conversation turn."""

    TABLE: ClassVar[str] = "chat_messages"

    user_id: str
    ts: datetime
    conversation_id: str
    trace_id: str
    role: str
    content: str
    # QuerySpec JSON of an answer, empty otherwise.
    query_spec: str
    turn: int
    revision: int
    # Shaped Result JSON of an answer, empty otherwise.
    result: str


class ConversationRecord(LogRecord):
    """One state of a conversation; the row with the latest ``updated_at`` wins."""

    TABLE: ClassVar[str] = "conversations"

    user_id: str
    conversation_id: str
    title: str
    pinned: bool
    group_id: str
    deleted: bool
    created_at: datetime
    updated_at: datetime
