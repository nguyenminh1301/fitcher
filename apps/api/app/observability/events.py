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
    # running, succeeded, failed, rejected or error
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


class EvalReportRecord(LogRecord):
    TABLE: ClassVar[str] = "eval_reports"

    pack: str
    ts: datetime
    report_id: str
    execution_rate: float
    passed: bool
    report: str
