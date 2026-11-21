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
from app.screening.screen import ScreenMode, Screener, Verdict
from app.search.engine import SearchEngine

TimeGrain = Literal["day", "week", "month", "quarter", "year"]


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
    search: SearchEngine
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
    # Screens the question before any LLM call; None refuses every question (fail closed).
    screener: Screener | None = None
    # log lets a blocked question continue and records it; enforce stops it.
    screen_mode: ScreenMode = "log"
    # Company documents are on (DECISIONS §15); off, metadata_qa answers without searching kb_docs.
    documents_enabled: bool = True
    # The clarifying options picked for ``question``, oldest first; the question is then the one that was clarified.
    choices: tuple[str, ...] = ()
    # What the user sent for this turn when it differs from ``question`` (the label of a picked option).
    asked: str = ""


class Attempt(BaseModel):
    """One SQL generation and what became of it."""

    model_config = ConfigDict(frozen=True)

    # The model tier the SQL was generated with.
    tier: str
    sql: str
    query_id: str | None = None
    error: AgentError | None = None


# Why a run ended with the blocked reply: the screen blocked the question, screening was
# unavailable, or the LLM gateway rejected a request.
BlockedReason = Literal["screened", "unavailable", "gateway"]


class AgentState(TypedDict, total=False):
    question: str
    trace_id: str
    # What the user sent when it differs from ``question``: the label of a clarifying option they picked.
    asked: str
    # The clarifying options the user picked for this question, as their ids ("period:this_year"), oldest first.
    choices: list[str]
    # The question covers all of the data: it said so, or the user picked "All data" for its period.
    all_time: bool
    # The screen node's verdict on the question, and why the run was stopped, if it was.
    screening: Verdict | None
    blocked: BlockedReason | None
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
    # The chart type a chart edit asks for, and the ChartSpec it got.
    chart_type: str | None
    chart_spec: BaseModel | None
    # The reply of a branch that answers without data: out_of_scope or metadata_qa.
    reply: str | None
    # The search hits metadata_qa answered from, as "<index>:<id>".
    sources: list[str]
    extraction: BaseModel | None
    periods: list[Period]
    retrieval: BaseModel | None
    spec: QuerySpec | None
    # The approved example whose reviewed spec build_spec used instead of resolving the terms.
    spec_example: str | None
    time_grain: TimeGrain | None
    # The SQL complexity rule's score of ``spec``: simple or standard.
    complexity: str | None
    sql: str | None
    attempts: list[Attempt]
    errors: list[AgentError]
    output: QueryOutput | None
    result: Result | None
    warnings: list[str]
    summary: str | None
    # Why the CLI entry point refused the question before any SQL was generated.
    rejection: str | None
    # The model call that reads the question failed (rate limit, outage); the run stops as a failure, not a refusal.
    model_error: str | None
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
