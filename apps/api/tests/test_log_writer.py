"""Agent log records and the batch writer, with a fake sink instead of ClickHouse."""

from datetime import datetime, UTC
from pathlib import Path
import re
import threading
import time

import pytest

from app.config import SettingsError, load_settings
from app.observability.events import (
    AdminActionRecord, AuditRecord, ChatMessageRecord, ConversationGroupRecord, ConversationRecord, EvalReportRecord, EventRecord, RunRecord,
    InputScreeningRecord, SqlRunRecord,
)
from app.observability.log_writer import ClickHouseLogSink, FlushResult, LogWriter

SCHEMA = Path(__file__).resolve().parents[3] / "infra" / "clickhouse" / "changes" / "0002_agent_logs.sql"
NOW = datetime(2026, 11, 2, 8, 0, tzinfo=UTC)


def table_columns(table: str) -> list[str]:
    sql = SCHEMA.read_text(encoding="utf-8")
    body = re.search(rf"CREATE TABLE IF NOT EXISTS agent_logs\.{table}\s*\((.*?)\n\)", sql, re.S).group(1)
    return [line.split()[0] for line in body.strip().splitlines()]


@pytest.mark.parametrize(
    "record", [
        RunRecord, EventRecord, SqlRunRecord, EvalReportRecord, AuditRecord, ChatMessageRecord, ConversationRecord,
        ConversationGroupRecord, InputScreeningRecord, AdminActionRecord,
    ],
)
def test_records_match_their_table_columns(record):
    assert list(record.model_fields) == table_columns(record.TABLE)


def event(trace_id: str = "t1", node: str = "extract") -> EventRecord:
    return EventRecord(
        trace_id=trace_id, ts=NOW, ended_at=NOW, node=node, status="ok", duration_ms=1, payload="{}",
        payload_truncated=False,
    )


class FakeSink:
    """Records inserts; ``fail`` raises before writing, ``fail_after_write`` writes and then raises."""

    def __init__(self, fail: int = 0, fail_after_write: int = 0, always_fail: bool = False, delay: float = 0.0):
        self.inserts: list[tuple[str, list[dict], str]] = []
        self.attempts: list[tuple[str, str]] = []
        self.fail = fail
        self.fail_after_write = fail_after_write
        self.always_fail = always_fail
        self.delay = delay
        self.lock = threading.Lock()

    def insert(self, table: str, rows: list[dict], token: str) -> None:
        time.sleep(self.delay)
        with self.lock:
            self.attempts.append((table, token))
            if self.always_fail or self.fail:
                self.fail = max(self.fail - 1, 0)
                raise ConnectionError("clickhouse unavailable")
            if any(token == written for _, _, written in self.inserts):
                return  # the server drops a block whose deduplication token it already has
            self.inserts.append((table, rows, token))
            if self.fail_after_write:
                self.fail_after_write -= 1
                raise TimeoutError("reply lost after the write")

    def rows(self) -> list[dict]:
        with self.lock:
            return [row for _, rows, _ in self.inserts for row in rows]


def writer(sink, batch_size=100, flush_interval_ms=60_000, queue_max=100, **kwargs) -> LogWriter:
    return LogWriter(
        sink, batch_size=batch_size, flush_interval_ms=flush_interval_ms, queue_max=queue_max, retry_delay=0, **kwargs
    ).start()


def eventually(condition, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.005)
    return condition()


def test_records_flush_when_a_batch_is_full():
    sink = FakeSink()
    log = writer(sink, batch_size=2)
    log.enqueue(event(node="a"))
    log.enqueue(event(node="b"))
    assert eventually(lambda: len(sink.rows()) == 2)
    assert [table for table, _, _ in sink.inserts] == ["events"]
    log.close()


def test_records_flush_at_the_interval():
    sink = FakeSink()
    log = writer(sink, flush_interval_ms=20)
    log.enqueue(event())
    assert eventually(lambda: len(sink.rows()) == 1)
    log.close()


def test_close_flushes_queued_records():
    sink = FakeSink()
    log = writer(sink)
    log.enqueue(event())
    log.close()
    assert len(sink.rows()) == 1


def test_flush_trace_reports_written_records():
    sink = FakeSink()
    log = writer(sink)
    for node in ("a", "b", "c"):
        log.enqueue(event(node=node))
    assert log.flush_trace("t1", timeout=2) == FlushResult(written=3, lost=0)
    log.close()


def test_overflow_counts_lost_records():
    sink = FakeSink(delay=0.2)
    log = writer(sink, queue_max=1, batch_size=1, flush_interval_ms=1)
    accepted = [log.enqueue(event(node=str(index))) for index in range(20)]
    assert not all(accepted)
    result = log.flush_trace("t1", timeout=10)
    assert result.lost == accepted.count(False)
    assert result.written + result.lost == 20
    log.close()


def test_first_batch_failure_is_retried_with_the_same_token():
    sink = FakeSink(fail=1)
    log = writer(sink)
    log.enqueue(event())
    assert log.flush_trace("t1", timeout=2) == FlushResult(written=1, lost=0)
    tokens = [token for _, token in sink.attempts]
    assert len(tokens) == 2 and tokens[0] == tokens[1]
    log.close()


def test_retry_of_a_batch_that_was_already_written_adds_no_rows():
    sink = FakeSink(fail_after_write=1)
    log = writer(sink)
    log.enqueue(event())
    assert log.flush_trace("t1", timeout=2) == FlushResult(written=1, lost=0)
    assert len(sink.attempts) == 2
    assert len(sink.rows()) == 1
    log.close()


def test_batch_failing_every_attempt_counts_its_records_lost():
    sink = FakeSink(always_fail=True)
    log = writer(sink, max_attempts=3)
    log.enqueue(event())
    log.enqueue(event(node="b"))
    assert log.flush_trace("t1", timeout=2) == FlushResult(written=0, lost=2)
    assert len(sink.attempts) == 3
    log.close()


def test_flush_trace_times_out_and_counts_pending_records_lost():
    sink = FakeSink(delay=1.0)
    log = writer(sink)
    log.enqueue(event())
    assert log.flush_trace("t1", timeout=0.05) == FlushResult(written=0, lost=1)
    log.close()


def test_flush_trace_counts_only_its_own_trace():
    sink = FakeSink(fail=1)
    log = writer(sink, batch_size=1)
    log.enqueue(event(trace_id="other"))
    log.enqueue(event(trace_id="t1"))
    log.enqueue(event(trace_id="t1", node="b"))
    assert log.flush_trace("t1", timeout=2) == FlushResult(written=2, lost=0)
    assert log.flush_trace("other", timeout=2) == FlushResult(written=1, lost=0)
    log.close()


def test_write_now_inserts_one_row_synchronously():
    sink = FakeSink()
    log = LogWriter(sink, batch_size=10, flush_interval_ms=60_000, queue_max=10, retry_delay=0)
    record = RunRecord(
        trace_id="t1", ts=NOW, updated_at=NOW, user_id="cli", pack="p", question="q", intent="", status="running",
        latency_ms=0, error="", log_complete=False, lost_records=0, llm_calls=0,
    )
    assert log.write_now(record) is True
    assert sink.inserts[0][0] == "runs"
    assert sink.inserts[0][1] == [record.model_dump()]


def test_write_now_failure_prints_the_trace_to_stderr(capsys):
    log = LogWriter(FakeSink(always_fail=True), batch_size=10, flush_interval_ms=60_000, queue_max=10, retry_delay=0)
    assert log.write_now(event(trace_id="abc123")) is False
    err = capsys.readouterr().err
    assert "abc123" in err and "ConnectionError" in err


def test_clickhouse_sink_connects_lazily_and_sends_the_token():
    calls = []

    class Client:
        def insert(self, table, data, column_names=None, database=None, settings=None):
            calls.append((table, data, column_names, database, settings))

    connects = []
    sink = ClickHouseLogSink(lambda: connects.append(1) or Client())
    assert connects == []
    sink.insert("events", [{"a": 1, "b": "x"}], "tok")
    sink.insert("events", [{"a": 2, "b": "y"}], "tok2")
    assert connects == [1]
    assert calls[0] == ("events", [[1, "x"]], ["a", "b"], "agent_logs", {"insert_deduplication_token": "tok"})


def test_clickhouse_sink_reconnects_after_a_failed_connect():
    attempts = []

    def connect():
        attempts.append(1)
        raise ConnectionError("down")

    sink = ClickHouseLogSink(connect)
    for _ in range(2):
        with pytest.raises(ConnectionError):
            sink.insert("events", [{"a": 1}], "tok")
    assert len(attempts) == 2


def test_log_settings_defaults_and_overrides():
    defaults = load_settings({})
    assert (defaults.log_batch_size, defaults.log_flush_interval_ms, defaults.log_queue_max) == (100, 1000, 10_000)
    custom = load_settings({"LOG_BATCH_SIZE": "5", "LOG_FLUSH_INTERVAL_MS": "50", "LOG_QUEUE_MAX": "7"})
    assert (custom.log_batch_size, custom.log_flush_interval_ms, custom.log_queue_max) == (5, 50, 7)


@pytest.mark.parametrize("name", ["LOG_BATCH_SIZE", "LOG_FLUSH_INTERVAL_MS", "LOG_QUEUE_MAX"])
def test_log_settings_must_be_positive(name):
    with pytest.raises(SettingsError, match=name):
        load_settings({name: "0"})
