"""The ``agent_logs.llm_calls`` row of one gateway call (DECISIONS §10).

The gateway builds one ``LlmCallRecord`` per call, whether the provider
answered, failed or screening refused the call, and hands it to the api's log
writer queue. Inside a run the row carries the run's ``trace_id`` and graph
node, so the trace compares the calls a run sent with the rows logged. The
cost is an estimate from the SDK's bundled price table; a model without a
known price logs a null cost, and the Costs page labels every cost as an
estimate. A failed write is reported on stderr and never fails the call.
"""

from collections.abc import Callable
from datetime import datetime, UTC
import sys
from typing import Any

from app.observability.events import LlmCallRecord

CallLog = Callable[[LlmCallRecord], object]
ERROR_LIMIT = 1000


def field(value: Any, name: str) -> Any:
    """An attribute of an SDK reply object, or a key of its dict form."""
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _count(usage: Any, name: str) -> int:
    return int(field(usage, name) or 0)


def estimate_cost(response: Any, model: str, call_type: str, api_base: str | None = None) -> float | None:
    """The call's cost in USD from LiteLLM's price table for the model called, or None when it has no known price.

    The price is looked up by the route's model, not the name a provider echoes in its reply, so an
    OpenAI-compatible server that reports a known model name is not priced as that model. A call to a free model
    or a provider's free tier costs nothing: LiteLLM's table holds the paid price of a model a free key uses.
    """
    from app.llm.catalog import free_call  # noqa: PLC0415 - the catalog imports the providers, which import this log
    from app.llm.gateway import litellm_module  # noqa: PLC0415 - shares the gateway's deferred import

    if free_call(model, api_base, call_type):
        return 0.0

    usage = field(response, "usage")
    try:
        prompt_cost, completion_cost = litellm_module().cost_per_token(
            model=model, prompt_tokens=_count(usage, "prompt_tokens"),
            completion_tokens=_count(usage, "completion_tokens"), call_type=call_type,
        )
    except Exception:  # noqa: BLE001 - a model the price table does not know
        return None
    return float(prompt_cost) + float(completion_cost)


def call_record(
    *, metadata: dict, tier: str, provider: str, model: str, started_at: datetime, latency_ms: int, status: str,
    error: str = "", response: Any = None, cost: float | None = None, fallback_of: str = "", call_id: str = "",
) -> LlmCallRecord:
    """The row of one call; its id is the provider's reply id, else ``call_id``, so a failed call has one too."""
    usage = field(response, "usage")
    return LlmCallRecord(
        trace_id=str(metadata.get("trace_id") or ""), ts=started_at, node=str(metadata.get("node") or ""),
        alias="", tier=tier, provider=provider, model=model, call_id=str(field(response, "id") or call_id),
        fallback_of=fallback_of,
        prompt_tokens=_count(usage, "prompt_tokens"), completion_tokens=_count(usage, "completion_tokens"),
        total_tokens=_count(usage, "total_tokens"), cost_usd=cost, latency_ms=max(latency_ms, 0), status=status,
        error=error[:ERROR_LIMIT],
    )


def write(call_log: CallLog | None, record: LlmCallRecord) -> None:
    if call_log is None:
        return
    try:
        call_log(record)
    except Exception as error:  # noqa: BLE001 - logging never fails the LLM call
        print(f"llm_calls write failed for trace {record.trace_id or '-'}: {type(error).__name__}", file=sys.stderr)


def now() -> datetime:
    return datetime.now(UTC)
