"""Write ``agent_logs`` records to ClickHouse without holding up the agent.

``write_now`` inserts one record synchronously; the api uses it for ``runs``
rows so a run's completeness marker never waits in the queue. ``enqueue`` puts
other records on a bounded queue that a background thread flushes in
per-table batches when a batch is full, at the flush interval, when a trace
asks for its records and on ``close``. The agent graph and its clients are
synchronous, so a thread, not an event loop, keeps writes off the run's path.

Each batch keeps one ``insert_deduplication_token`` for all its attempts, so
retrying a batch that ClickHouse already stored adds no rows. Records are
counted per trace as written or lost (queue full, every attempt failed, or
still pending when ``flush_trace`` timed out); a logging failure never raises
into the caller.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from itertools import groupby
import os
import queue
import sys
import threading
import time
from typing import Protocol
from uuid import uuid4

import clickhouse_connect

from app.config import Settings
from app.observability.events import LogRecord

LOGS_DATABASE = "agent_logs"
DEFAULT_WRITER_USER = "agent_logs_writer"
ERROR_LIMIT = 300
_STOP = object()
_WAKE = object()


class LogSink(Protocol):
    def insert(self, table: str, rows: list[dict], token: str) -> None:
        """Insert ``rows`` into ``table`` with ``token`` as the deduplication token."""


class ClickHouseLogSink:
    """Inserts through a client created on first use, so ClickHouse being down only fails writes."""

    def __init__(self, connect: Callable[[], object]):
        self._connect = connect
        self._client = None
        self._lock = threading.Lock()

    def insert(self, table: str, rows: list[dict], token: str) -> None:
        with self._lock:
            if self._client is None:
                self._client = self._connect()
            columns = list(rows[0])
            self._client.insert(
                table, [[row[column] for column in columns] for row in rows], column_names=columns,
                database=LOGS_DATABASE, settings={"insert_deduplication_token": token},
            )


def writer_client(env: Mapping[str, str] | None = None):
    env = os.environ if env is None else env
    password = env.get("CLICKHOUSE_LOGS_WRITER_PASSWORD", "")
    if not password:
        raise RuntimeError("CLICKHOUSE_LOGS_WRITER_PASSWORD must be set")
    return clickhouse_connect.get_client(
        host=env.get("CLICKHOUSE_HOST", "clickhouse"),
        port=int(env.get("CLICKHOUSE_HTTP_PORT", "8123")),
        username=env.get("CLICKHOUSE_LOGS_WRITER_USER", DEFAULT_WRITER_USER),
        password=password,
        database=LOGS_DATABASE,
        # Shared across concurrent requests: a session would serialize them and refuse overlaps.
        autogenerate_session_id=False,
    )


@dataclass(frozen=True)
class FlushResult:
    written: int
    lost: int


def _trace(record: LogRecord) -> str:
    return getattr(record, "trace_id", "")


def _describe(error: Exception) -> str:
    return f"{type(error).__name__}: {str(error)[:ERROR_LIMIT]}"


class LogWriter:
    def __init__(
        self,
        sink: LogSink,
        *,
        batch_size: int,
        flush_interval_ms: int,
        queue_max: int,
        max_attempts: int = 3,
        retry_delay: float = 0.2,
    ):
        self._sink = sink
        self._batch_size = batch_size
        self._interval = flush_interval_ms / 1000
        self._max_attempts = max_attempts
        self._retry_delay = retry_delay
        self._queue: queue.Queue = queue.Queue(maxsize=queue_max)
        self._cond = threading.Condition()
        # Per-trace counters; a trace drops out once flush_trace has reported it.
        self._pending: dict[str, int] = {}
        self._written: dict[str, int] = {}
        self._lost: dict[str, int] = {}
        self._flush_now = threading.Event()
        self._thread = threading.Thread(target=self._run, name="agent-log-writer", daemon=True)

    def start(self) -> "LogWriter":
        self._thread.start()
        return self

    def write_now(self, record: LogRecord) -> bool:
        error = self._insert(record.TABLE, [record.model_dump()])
        if error is None:
            return True
        print(f"agent log write failed for trace {_trace(record) or '-'} ({record.TABLE}): {_describe(error)}", file=sys.stderr)
        return False

    def enqueue(self, record: LogRecord) -> bool:
        trace = _trace(record)
        with self._cond:
            self._pending[trace] = self._pending.get(trace, 0) + 1
        try:
            self._queue.put_nowait(record)
            return True
        except queue.Full:
            with self._cond:
                if trace in self._pending:
                    self._pending[trace] -= 1
                    self._lost[trace] = self._lost.get(trace, 0) + 1
                self._cond.notify_all()
            return False

    def flush_trace(self, trace_id: str, timeout: float = 5.0) -> FlushResult:
        """Flush now and wait for ``trace_id``'s records; records still pending at the timeout count as lost."""
        self._wake()
        with self._cond:
            self._cond.wait_for(lambda: self._pending.get(trace_id, 0) == 0, timeout)
            pending = self._pending.pop(trace_id, 0)
            return FlushResult(written=self._written.pop(trace_id, 0), lost=self._lost.pop(trace_id, 0) + pending)

    def close(self, timeout: float = 5.0) -> None:
        if not self._thread.is_alive():
            return
        try:
            self._queue.put(_STOP, timeout=timeout)
        except queue.Full:
            return
        self._thread.join(timeout)

    def _wake(self) -> None:
        self._flush_now.set()
        try:
            self._queue.put_nowait(_WAKE)
        except queue.Full:
            pass  # the worker is busy with a full queue and checks the flag after its next item

    def _run(self) -> None:
        buffer: list[LogRecord] = []
        deadline = time.monotonic() + self._interval
        stopping = False
        while not stopping:
            try:
                item = self._queue.get(timeout=max(deadline - time.monotonic(), 0))
            except queue.Empty:
                item = None
            if item is _STOP:
                stopping = True
            elif item is not None and item is not _WAKE:
                buffer.append(item)
            urgent = stopping or self._flush_now.is_set()
            if urgent:
                self._flush_now.clear()
                stopping = self._drain(buffer) or stopping
            if urgent or len(buffer) >= self._batch_size or time.monotonic() >= deadline:
                if buffer:
                    self._write(buffer)
                    buffer = []
                deadline = time.monotonic() + self._interval

    def _drain(self, buffer: list[LogRecord]) -> bool:
        """Move every queued record into ``buffer``; True when the stop marker was among them."""
        stop = False
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                return stop
            if item is _STOP:
                stop = True
            elif item is not _WAKE:
                buffer.append(item)

    def _write(self, records: list[LogRecord]) -> None:
        records = sorted(records, key=lambda record: record.TABLE)
        for table, group in groupby(records, key=lambda record: record.TABLE):
            rows = list(group)
            for start in range(0, len(rows), self._batch_size):
                batch = rows[start:start + self._batch_size]
                error = self._insert(table, [record.model_dump() for record in batch])
                if error is not None:
                    print(f"agent log batch of {len(batch)} {table} rows lost: {_describe(error)}", file=sys.stderr)
                self._settle(batch, written=error is None)

    def _insert(self, table: str, rows: list[dict]) -> Exception | None:
        token = uuid4().hex
        error: Exception | None = None
        for attempt in range(self._max_attempts):
            if attempt:
                time.sleep(self._retry_delay * attempt)
            try:
                self._sink.insert(table, rows, token)
                return None
            except Exception as caught:  # noqa: BLE001 - a log write never fails the run
                error = caught
        return error

    def _settle(self, batch: list[LogRecord], written: bool) -> None:
        outcome = self._written if written else self._lost
        with self._cond:
            for record in batch:
                trace = _trace(record)
                if trace not in self._pending:
                    continue  # already reported by flush_trace as lost
                self._pending[trace] -= 1
                outcome[trace] = outcome.get(trace, 0) + 1
            self._cond.notify_all()


def start_log_writer(settings: Settings) -> LogWriter:
    return LogWriter(
        ClickHouseLogSink(writer_client),
        batch_size=settings.log_batch_size,
        flush_interval_ms=settings.log_flush_interval_ms,
        queue_max=settings.log_queue_max,
    ).start()
