"""OpenTelemetry spans for agent runs and their nodes.

``run_span`` opens the root span of a run; its 32-hex trace id is the run's
``trace_id`` everywhere: graph state, ``log_comment`` on ClickHouse queries,
``agent_logs`` rows and LiteLLM request metadata. ``node_span`` opens a child
span per graph node. The provider has no exporter: the lab keeps traces in
``agent_logs`` (DECISIONS §10), not in a tracing backend.

The current run travels in a context variable, so the LLM clients can tag
their requests without any change to node signatures.
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


_RUN: ContextVar[RunContext | None] = ContextVar("agent_run", default=None)


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


def llm_metadata() -> dict:
    """Count one gateway request of the current run and return its LiteLLM metadata; empty outside a run."""
    run = _RUN.get()
    if run is None:
        return {}
    run.llm_calls += 1
    return {"trace_id": run.trace_id, "node": run.node}
