"""The LiteLLM proxy callback that writes ``agent_logs.llm_calls``, loaded from its file without litellm."""

import asyncio
import importlib.util
import json
from pathlib import Path
import re

import httpx

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = ROOT / "infra" / "clickhouse" / "changes" / "0002_agent_logs.sql"


def load_callback():
    spec = importlib.util.spec_from_file_location("clickhouse_logger", ROOT / "infra" / "litellm" / "callbacks" / "clickhouse_logger.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


callback = load_callback()


def payload(**overrides) -> dict:
    base = {
        "id": "call-1", "model_group": "openai-medium", "model": "gpt-5.4", "status": "success",
        "prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150, "response_cost": 0.0042,
        "startTime": 1793606400.0, "endTime": 1793606401.25, "error_str": None,
        "metadata": {"requester_metadata": {"trace_id": "ab" * 16, "node": "generate_sql", "tier": "sql-gen"}},
    }
    return {**base, **overrides}


def test_row_has_the_llm_calls_columns():
    sql = SCHEMA.read_text(encoding="utf-8")
    body = re.search(r"CREATE TABLE IF NOT EXISTS agent_logs\.llm_calls\s*\((.*?)\n\)", sql, re.S).group(1)
    assert list(callback.build_row(payload())) == [line.split()[0] for line in body.strip().splitlines()]


def test_success_row():
    row = callback.build_row(payload())
    assert row == {
        "trace_id": "ab" * 16, "ts": "2026-11-02 08:00:00.000", "node": "generate_sql", "alias": "openai-medium",
        "tier": "sql-gen", "model": "gpt-5.4", "call_id": "call-1", "prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150,
        "cost_usd": 0.0042, "latency_ms": 1250, "status": "success", "error": "",
    }


def test_failure_row_keeps_the_error():
    row = callback.build_row(payload(status="failure", error_str="RateLimitError: slow down", response_cost=None,
                                     prompt_tokens=None, completion_tokens=None, total_tokens=None))
    assert (row["status"], row["error"], row["cost_usd"], row["total_tokens"]) == ("failure", "RateLimitError: slow down", 0.0, 0)


def test_call_without_metadata_has_empty_trace_and_node():
    row = callback.build_row(payload(metadata={}))
    assert (row["trace_id"], row["node"], row["tier"]) == ("", "", "")
    assert callback.build_row(payload(metadata=None))["trace_id"] == ""


def test_insert_posts_json_each_row_as_the_writer(monkeypatch):
    monkeypatch.setenv("CLICKHOUSE_HOST", "ch")
    monkeypatch.setenv("CLICKHOUSE_LOGS_WRITER_PASSWORD", "secret")
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200)

    row = callback.build_row(payload())
    asyncio.run(callback.insert_row(row, transport=httpx.MockTransport(handler)))
    request = sent[0]
    assert str(request.url).startswith("http://ch:8123/?")
    assert request.url.params["query"] == "INSERT INTO agent_logs.llm_calls FORMAT JSONEachRow"
    assert request.headers["Authorization"].startswith("Basic ")
    assert json.loads(request.content) == row


def test_a_write_failure_is_reported_and_never_raised(monkeypatch, capsys):
    monkeypatch.setenv("CLICKHOUSE_LOGS_WRITER_PASSWORD", "secret")

    async def fail(row, transport=None):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(callback, "insert_row", fail)
    logger = callback.ClickHouseLogger()
    asyncio.run(logger.async_log_success_event({"standard_logging_object": payload()}, None, None, None))
    asyncio.run(logger.async_log_failure_event({}, None, None, None))
    err = capsys.readouterr().err
    assert "llm_calls write failed for trace " + "ab" * 16 in err and "ConnectError" in err
