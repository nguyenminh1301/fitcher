"""LiteLLM proxy callback that writes one ``agent_logs.llm_calls`` row per gateway call.

The api sends each request's ``trace_id`` and graph node as request
``metadata``; LiteLLM passes it back in ``standard_logging_object`` as
``metadata.requester_metadata``. Calls made outside a traced run (pack
compiles, smoke tests) are written with an empty trace id and node.

Rows go to the ClickHouse HTTP interface as the insert-only
``agent_logs_writer`` (``CLICKHOUSE_LOGS_WRITER_PASSWORD``), using the httpx
client LiteLLM already ships. A failed write is printed to stderr and never
affects the LLM response. LiteLLM's built-in ClickHouse logger is not used
because it writes its own spend-log schema, not the ``llm_calls`` columns.

``infra/litellm/config.yaml`` loads ``proxy_handler_instance`` from this file,
which compose mounts next to the config.
"""

from datetime import datetime, UTC
import json
import os
import sys

import httpx

try:
    from litellm.integrations.custom_logger import CustomLogger
except ImportError:  # unit tests load this file without litellm installed
    CustomLogger = object

INSERT = "INSERT INTO agent_logs.llm_calls FORMAT JSONEachRow"
ERROR_LIMIT = 1000
TIMEOUT_SECONDS = 5


def _timestamp(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _count(value) -> int:
    return int(value or 0)


def build_row(payload: dict) -> dict:
    """The ``llm_calls`` row of one LiteLLM ``StandardLoggingPayload``."""
    requester = (payload.get("metadata") or {}).get("requester_metadata") or {}
    start = float(payload.get("startTime") or 0)
    end = float(payload.get("endTime") or start)
    return {
        "trace_id": str(requester.get("trace_id") or ""),
        "ts": _timestamp(start),
        "node": str(requester.get("node") or ""),
        "alias": payload.get("model_group") or "",
        "model": payload.get("model") or "",
        "call_id": payload.get("id") or "",
        "prompt_tokens": _count(payload.get("prompt_tokens")),
        "completion_tokens": _count(payload.get("completion_tokens")),
        "total_tokens": _count(payload.get("total_tokens")),
        "cost_usd": float(payload.get("response_cost") or 0),
        "latency_ms": max(round((end - start) * 1000), 0),
        "status": payload.get("status") or "",
        "error": (payload.get("error_str") or "")[:ERROR_LIMIT],
    }


async def insert_row(row: dict, transport: httpx.AsyncBaseTransport | None = None) -> None:
    host = os.environ.get("CLICKHOUSE_HOST", "clickhouse")
    port = os.environ.get("CLICKHOUSE_HTTP_PORT", "8123")
    auth = (os.environ.get("CLICKHOUSE_LOGS_WRITER_USER", "agent_logs_writer"), os.environ.get("CLICKHOUSE_LOGS_WRITER_PASSWORD", ""))
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, transport=transport) as client:
        response = await client.post(f"http://{host}:{port}/", params={"query": INSERT}, content=json.dumps(row), auth=auth)
        response.raise_for_status()


class ClickHouseLogger(CustomLogger):
    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        await self._write(kwargs)

    async def async_log_failure_event(self, kwargs, response_obj, start_time, end_time):
        await self._write(kwargs)

    async def _write(self, kwargs: dict) -> None:
        payload = kwargs.get("standard_logging_object")
        if not payload:
            return
        row = build_row(payload)
        try:
            await insert_row(row)
        except Exception as error:  # noqa: BLE001 - logging never fails the LLM call
            print(f"llm_calls write failed for trace {row['trace_id'] or '-'}: {type(error).__name__}: {str(error)[:300]}", file=sys.stderr)


proxy_handler_instance = ClickHouseLogger()
