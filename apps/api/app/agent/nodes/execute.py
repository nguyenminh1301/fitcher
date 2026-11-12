"""Run the guarded SQL as the read-only agent user (DECISIONS §6 step 12).

A result whose columns share a name is an ``sql`` error, so it is repaired
like any other query the generator got wrong.
"""

from collections import Counter
from dataclasses import dataclass
from typing import Protocol

from app.agent.audit import audit
from app.agent.errors import ACCESS_DENIED, AgentError
from app.data.clickhouse import QueryError, QueryOutput
from app.agent.state import AgentDeps, AgentState, record_error

NODE = "execute"


class Runner(Protocol):
    def run(self, sql: str, trace_id: str) -> QueryOutput: ...


@dataclass(frozen=True)
class ExecutionResult:
    output: QueryOutput | None = None
    error: AgentError | None = None
    query_id: str | None = None


def _repeated_columns(columns: list[str]) -> list[str]:
    return [name for name, count in Counter(columns).items() if count > 1]


def execute(runner: Runner, sql: str, trace_id: str) -> ExecutionResult:
    try:
        output = runner.run(sql, trace_id)
    except QueryError as error:
        return ExecutionResult(error=AgentError(error.category, NODE, error.message, error.code), query_id=error.query_id)
    # ClickHouse returns a repeated expression (SELECT a, a) under one name twice; a Result cannot hold
    # it, so the generator is asked for distinct aliases instead of failing the run.
    if repeated := _repeated_columns(output.columns):
        message = f"the query returns more than one column named {', '.join(repeated)}; give every column a distinct name"
        return ExecutionResult(error=AgentError("sql", NODE, message), query_id=output.query_id)
    return ExecutionResult(output=output, query_id=output.query_id)


def execute_node(state: AgentState, deps: AgentDeps) -> dict:
    result = execute(deps.runner, state["sql"], state["trace_id"])
    if result.error is not None:
        if result.error.code == ACCESS_DENIED:
            audit(state, deps, "DENY", state["spec"].dataset, [], f"clickhouse: {result.error.message}")
        return record_error(state, result.error, result.query_id)
    attempts = list(state["attempts"])
    attempts[-1] = attempts[-1].model_copy(update={"query_id": result.query_id})
    return {"output": result.output, "attempts": attempts}
