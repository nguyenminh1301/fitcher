"""Ask ClickHouse to plan the guarded SQL before running it (DECISIONS §6 step 11).

``EXPLAIN`` catches unknown columns, type errors and missing functions without
reading data, so a broken query is sent back for repair cheaply.
"""

from typing import Protocol

from app.agent.errors import AgentError
from app.data.clickhouse import QueryError
from app.agent.state import AgentDeps, AgentState, record_error

NODE = "explain"


class Explainer(Protocol):
    def explain(self, sql: str, trace_id: str) -> str: ...


def explain(runner: Explainer, sql: str, trace_id: str) -> AgentError | None:
    """Return None when ClickHouse can plan the query, else the classified error."""
    try:
        runner.explain(sql, trace_id)
    except QueryError as error:
        return AgentError(error.category, NODE, error.message)
    return None


def explain_node(state: AgentState, deps: AgentDeps) -> dict:
    error = explain(deps.runner, state["sql"], state["trace_id"])
    return record_error(state, error) if error is not None else {}
