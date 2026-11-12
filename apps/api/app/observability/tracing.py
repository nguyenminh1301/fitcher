"""OpenTelemetry spans for agent runs and their nodes.

``run_span`` opens the root span of a run; its 32-hex trace id is the run's
``trace_id`` everywhere: graph state, ``log_comment`` on ClickHouse queries,
``agent_logs`` rows and LiteLLM request metadata. ``node_span`` opens a child
span per graph node. The provider has no exporter: the lab keeps traces in
``agent_logs`` (DECISIONS §10), not in a tracing backend.

The current run travels in a context variable, so the LLM clients can tag
their requests without any change to node signatures. Every gateway request
also carries ``screening`` metadata, which the LiteLLM guardrail requires
(DECISIONS §9): inside a run it is the verdict the ``screen`` node recorded
(``allow`` or ``flag``), and calls on reviewed pack content outside a run
(compiles, smoke tests) run inside ``trusted_pack_calls``. A request with
neither is sent without it and the gateway rejects it.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from opentelemetry.sdk.trace import TracerProvider

_tracer = TracerProvider().get_tracer("fitcher.agent")


@dataclass
class RunContext:
    trace_id: str
    node: str = ""
    # Gateway requests sent during the run, compared with llm_calls rows by the trace query.
    llm_calls: int = 0
    # The question's screening metadata for the gateway, set by the screen node: allow or flag.
    screening: str = ""


_RUN: ContextVar[RunContext | None] = ContextVar("agent_run", default=None)
_TRUSTED: ContextVar[bool] = ContextVar("trusted_pack_calls", default=False)
TRUSTED_PACK = "trusted_pack"


def current_run() -> RunContext | None:
    return _RUN.get()


@contextmanager
def run_span() -> Iterator[RunContext]:
    with _tracer.start_as_current_span("agent.run") as span:
        run = RunContext(trace_id=format(span.get_span_context().trace_id, "032x"))
        token = _RUN.set(run)
        try:
            yield run
        finally:
            _RUN.reset(token)


@contextmanager
def node_span(name: str) -> Iterator[None]:
    run = _RUN.get()
    previous = run.node if run else ""
    with _tracer.start_as_current_span(name):
        if run:
            run.node = name
        try:
            yield
        finally:
            if run:
                run.node = previous


@contextmanager
def trusted_pack_calls() -> Iterator[None]:
    """Mark the gateway requests sent outside a run inside this block as calls on reviewed pack content."""
    token = _TRUSTED.set(True)
    try:
        yield
    finally:
        _TRUSTED.reset(token)


def llm_metadata() -> dict:
    """Count one gateway request of the current run and return its LiteLLM metadata.

    Outside a run the metadata is ``trusted_pack`` screening inside ``trusted_pack_calls`` and empty otherwise.
    """
    run = _RUN.get()
    if run is None:
        return {"screening": TRUSTED_PACK} if _TRUSTED.get() else {}
    run.llm_calls += 1
    metadata = {"trace_id": run.trace_id, "node": run.node}
    if run.screening:
        metadata["screening"] = run.screening
    return metadata
