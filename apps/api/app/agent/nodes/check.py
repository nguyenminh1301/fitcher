"""Decide what follows a SQL attempt (DECISIONS §6 step 13).

A ``policy`` error stops the run without a retry. An ``sql`` or ``runtime``
error returns to ``generate_sql`` until four generations (one initial plus
three retries) have run; then the run ends with the last SQL and error and no
result. A query that returned rows, or none, goes on to ``shape_result``; an
empty result carries a warning.
"""

from typing import Literal

from app.agent.nodes.generate_sql import MAX_GENERATIONS
from app.agent.state import AgentDeps, AgentState

Route = Literal["retry", "shape", "stop"]


def route(state: AgentState) -> Route:
    if state.get("output") is not None:
        return "shape"
    error = state["attempts"][-1].error
    if error is None or error.category == "policy":
        return "stop"
    return "retry" if len(state["attempts"]) < MAX_GENERATIONS else "stop"


def check(state: AgentState, deps: AgentDeps) -> dict:
    output = state.get("output")
    if output is not None and not output.rows:
        return {"warnings": [*state.get("warnings", []), "the query returned no rows"]}
    return {}
