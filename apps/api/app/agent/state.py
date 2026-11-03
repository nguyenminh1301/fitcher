"""Graph state and the dependencies the nodes receive.

Each node is a function of ``(state, deps)`` that returns the state fields it
changes, so it can be tested alone with fake dependencies (DECISIONS §13).
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Literal, Protocol, TypedDict

from pydantic import BaseModel, ConfigDict

from app.agent.errors import AgentError
from app.contracts.query_spec import Period, QuerySpec
from app.contracts.result import Result
from app.conversation.store import Turn
from app.data.clickhouse import QueryOutput
from app.llm.client import LLMClient
from app.llm.embeddings import EmbeddingClient
from app.observability.events import LogRecord
from app.observability.log_writer import FlushResult
from app.packs.compiler import CompiledPack
from app.packs.models import BusinessProfile

TimeGrain = Literal["day", "week", "month", "quarter", "year"]


class SearchClient(Protocol):
    def search(self, index: str, body: dict, pipeline: str | None = None) -> list[dict]: ...


class LogWriter(Protocol):
    def write_now(self, record: LogRecord) -> bool: ...

    def enqueue(self, record: LogRecord) -> bool: ...

    def flush_trace(self, trace_id: str, timeout: float = 5.0) -> FlushResult: ...

    def close(self, timeout: float = 5.0) -> None: ...


class QueryRunner(Protocol):
    def explain(self, sql: str, trace_id: str) -> str: ...

    def run(self, sql: str, trace_id: str) -> QueryOutput: ...


class RunCancelled(Exception):
    """Raised by a progress callback to stop the run at the next node; the run is logged as cancelled."""


# Called with the node name, "start" or "end", the state the node received and, at the end, its update.
Progress = Callable[[str, Literal["start", "end"], "AgentState", Mapping | None], None]


@dataclass(frozen=True)
class AgentDeps:
    llm: LLMClient
    search: SearchClient
    embeddings: EmbeddingClient
    runner: QueryRunner
    compiled: CompiledPack
    today: date
    # agent_logs writer; None runs the graph without logging (unit tests).
    logs: LogWriter | None = None
    # Who asked; written to the run row.
    user_id: str = ""
    # The pack role the question is asked as: it filters retrieval, picks the guard's allowlist
    # and names the ClickHouse user that ``runner`` connects as.
    role: str = ""
    # Told when each node starts and ends (the api streams it); it may raise RunCancelled.
    progress: Progress | None = None
    # The conversation's current thread before this question, oldest first; empty for a new conversation.
    history: tuple[Turn, ...] = ()


class Attempt(BaseModel):
    """One SQL generation and what became of it."""

    model_config = ConfigDict(frozen=True)

    alias: str
    sql: str
    query_id: str | None = None
    error: AgentError | None = None


class AgentState(TypedDict, total=False):
    question: str
    trace_id: str
    profile: BusinessProfile
    # The last turns of the conversation and the latest QuerySpec and result among them.
    history: list[Turn]
    previous_spec: QuerySpec | None
    previous_result: Result | None
    # The router's intent; intent_fallback is set when it was uncertain and data_query was assumed.
    intent: str
    intent_fallback: bool
    # The question's language as the router read it; None when it could not.
    language: str | None
    # The out_of_scope branch's reply.
    reply: str | None
    extraction: BaseModel | None
    periods: list[Period]
    retrieval: BaseModel | None
    spec: QuerySpec | None
    time_grain: TimeGrain | None
    sql: str | None
    attempts: list[Attempt]
    errors: list[AgentError]
    output: QueryOutput | None
    result: Result | None
    warnings: list[str]
    summary: str | None
    # Why the CLI entry point refused the question before any SQL was generated.
    rejection: str | None
    # The gate's denial: what the asking role may not read, and the message for the user.
    denial: BaseModel | None
    # What build_spec could not settle, and the gate's clarifying question about it.
    need: BaseModel | None
    clarification: BaseModel | None


def record_error(state: AgentState, error: AgentError, query_id: str | None = None) -> dict:
    """State update that attaches ``error`` to the latest attempt and the run's error list."""
    attempts = list(state.get("attempts", []))
    if attempts:
        attempts[-1] = attempts[-1].model_copy(update={"error": error, "query_id": query_id or attempts[-1].query_id})
    return {"attempts": attempts, "errors": [*state.get("errors", []), error]}
