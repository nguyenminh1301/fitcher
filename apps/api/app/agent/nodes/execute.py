"""Run the guarded SQL as the read-only agent user (DECISIONS §6 step 12)."""

from dataclasses import dataclass
from typing import Protocol

from app.agent.errors import AgentError
from app.data.clickhouse import QueryError, QueryOutput

NODE = "execute"


class Runner(Protocol):
    def run(self, sql: str, trace_id: str) -> QueryOutput: ...


@dataclass(frozen=True)
class ExecutionResult:
    output: QueryOutput | None = None
    error: AgentError | None = None
    query_id: str | None = None


def execute(runner: Runner, sql: str, trace_id: str) -> ExecutionResult:
    try:
        output = runner.run(sql, trace_id)
    except QueryError as error:
        return ExecutionResult(error=AgentError(error.category, NODE, error.message), query_id=error.query_id)
    return ExecutionResult(output=output, query_id=output.query_id)
