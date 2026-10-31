"""Graph state and the dependencies the nodes receive.

Each node is a function of ``(state, deps)`` that returns the state fields it
changes, so it can be tested alone with fake dependencies (DECISIONS §13).
"""

from dataclasses import dataclass
from datetime import date
from typing import Literal, Protocol, TypedDict

from pydantic import BaseModel, ConfigDict

from app.agent.errors import AgentError
from app.contracts.query_spec import Period, QuerySpec
from app.contracts.result import Result
from app.data.clickhouse import QueryOutput
from app.llm.client import LLMClient
from app.llm.embeddings import EmbeddingClient
from app.packs.compiler import CompiledPack
from app.packs.models import BusinessProfile

TimeGrain = Literal["day", "week", "month", "quarter", "year"]


class SearchClient(Protocol):
    def search(self, index: str, body: dict, pipeline: str | None = None) -> list[dict]: ...


class QueryRunner(Protocol):
    def explain(self, sql: str, trace_id: str) -> str: ...

    def run(self, sql: str, trace_id: str) -> QueryOutput: ...


@dataclass(frozen=True)
class AgentDeps:
    llm: LLMClient
    search: SearchClient
    embeddings: EmbeddingClient
    runner: QueryRunner
    compiled: CompiledPack
    today: date


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


def record_error(state: AgentState, error: AgentError, query_id: str | None = None) -> dict:
    """State update that attaches ``error`` to the latest attempt and the run's error list."""
    attempts = list(state.get("attempts", []))
    if attempts:
        attempts[-1] = attempts[-1].model_copy(update={"error": error, "query_id": query_id or attempts[-1].query_id})
    return {"attempts": attempts, "errors": [*state.get("errors", []), error]}
