"""The ``runs`` rows of one traced run.

A ``running`` row is written synchronously before the graph starts and the
final row synchronously after the run's queued records were flushed, so the
completeness marker never depends on the batch queue. ``log_complete`` is true
only when the running row and every queued record of the run reached
ClickHouse; a failed write of either row is reported on stderr by the writer.
"""

import time
from typing import Protocol

from app.observability.events import LogRecord, RunRecord, utc_now
from app.observability.log_writer import FlushResult
from app.observability.tracing import RunContext

FLUSH_TIMEOUT_SECONDS = 5.0
ERROR_LIMIT = 1000


class RunLogWriter(Protocol):
    def write_now(self, record: LogRecord) -> bool: ...

    def flush_trace(self, trace_id: str, timeout: float = 5.0) -> FlushResult: ...


class RunLog:
    def __init__(self, logs: RunLogWriter, run: RunContext, *, user_id: str, pack: str, question: str):
        self._logs = logs
        self._run = run
        self._fields = {"trace_id": run.trace_id, "ts": utc_now(), "user_id": user_id, "pack": pack, "question": question}
        self._started = time.monotonic()
        self._running_written = logs.write_now(self._record("running", intent="", error=""))

    def finish(self, status: str, *, intent: str, error: str) -> None:
        flush = self._logs.flush_trace(self._run.trace_id, FLUSH_TIMEOUT_SECONDS)
        self._logs.write_now(self._record(
            status, intent=intent, error=error, latency_ms=round((time.monotonic() - self._started) * 1000),
            log_complete=self._running_written and flush.lost == 0, lost_records=flush.lost,
        ))

    def _record(
        self, status: str, *, intent: str, error: str, latency_ms: int = 0, log_complete: bool = False,
        lost_records: int = 0,
    ) -> RunRecord:
        return RunRecord(
            **self._fields, updated_at=utc_now(), intent=intent, status=status, latency_ms=latency_ms,
            error=error[:ERROR_LIMIT], log_complete=log_complete, lost_records=lost_records,
            llm_calls=self._run.llm_calls,
        )
