"""Node events and SQL attempts of a logged run.

``instrument`` wraps a graph node without changing its ``(state, deps)``
signature: it tells ``deps.progress`` when the node starts and ends, opens the
node's span and queues one ``events`` row with the node's start, end, status
and state update as a JSON payload. Payloads are
capped at 16 KB and never hold result rows, only their count.
``LoggingRunner`` queues one ``sql_runs`` row per query the run executes.
"""

from collections.abc import Callable, Mapping
from dataclasses import asdict, is_dataclass
from functools import wraps
import json
import time

from pydantic import BaseModel

from app.data.clickhouse import QueryError, QueryOutput
from app.observability.events import EventRecord, SqlRunRecord, utc_now
from app.observability.tracing import node_span

PAYLOAD_LIMIT = 16_384
ERROR_LIMIT = 1000


def _jsonable(value: object) -> object:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    elif is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)
    if isinstance(value, Mapping):
        fields = {str(key): _jsonable(item) for key, item in value.items() if key != "rows"}
        if isinstance(value.get("rows"), list | tuple):
            fields.setdefault("row_count", len(value["rows"]))
        return fields
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value


def payload_json(update: Mapping) -> tuple[str, bool]:
    """``update`` as JSON without result rows, and whether it was cut at ``PAYLOAD_LIMIT`` bytes."""
    text = json.dumps(_jsonable(update), ensure_ascii=False, default=str)
    data = text.encode("utf-8")
    if len(data) <= PAYLOAD_LIMIT:
        return text, False
    return data[:PAYLOAD_LIMIT].decode("utf-8", errors="ignore"), True


def instrument(name: str, node: Callable) -> Callable:
    @wraps(node)
    def wrapper(state, deps):
        started, clock = utc_now(), time.monotonic()

        def log(status: str, payload: Mapping) -> None:
            if deps.logs is None:
                return
            text, truncated = payload_json(payload)
            deps.logs.enqueue(EventRecord(
                trace_id=state["trace_id"], ts=started, ended_at=utc_now(), node=name, status=status,
                duration_ms=round((time.monotonic() - clock) * 1000), payload=text, payload_truncated=truncated,
            ))

        if deps.progress is not None:
            deps.progress(name, "start", state, None)
        with node_span(name):
            try:
                update = node(state, deps)
            except Exception as error:
                log("error", {"error": f"{type(error).__name__}: {error}"})
                raise
        log("ok", update or {})
        if deps.progress is not None:
            deps.progress(name, "end", state, update or {})
        return update

    return wrapper


class LoggingRunner:
    """Wraps the query runner of one run; ``attempt`` counts the run's executions from 1."""

    def __init__(self, inner, logs):
        self._inner = inner
        self._logs = logs
        self._attempts = 0

    def explain(self, sql: str, trace_id: str) -> str:
        return self._inner.explain(sql, trace_id)

    def run(self, sql: str, trace_id: str) -> QueryOutput:
        self._attempts += 1
        record = {"trace_id": trace_id, "ts": utc_now(), "attempt": self._attempts, "sql": sql}
        try:
            output = self._inner.run(sql, trace_id)
        except Exception as error:
            if isinstance(error, QueryError):
                query_id, message = error.query_id or "", f"{error.category}: {error.message}"
            else:
                query_id, message = "", f"{type(error).__name__}: {error}"
            self._logs.enqueue(SqlRunRecord(**record, query_id=query_id, rows=0, error=message[:ERROR_LIMIT]))
            raise
        self._logs.enqueue(SqlRunRecord(**record, query_id=output.query_id, rows=len(output.rows), error=""))
        return output
