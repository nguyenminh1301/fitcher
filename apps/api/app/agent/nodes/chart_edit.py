"""Redraw the previous answer (DECISIONS §6 step 3).

A chart edit reuses the QuerySpec and shaped Result stored with the previous
turn and draws it as the type the router read from the question when the
DECISIONS §8 rules allow that type, otherwise as the rules choose, a tie
keeping their pick. It never generates or runs SQL and calls no LLM; the graph
sends a chart edit without a previous result through the data question flow
instead.
"""

from app.agent.chart_rules import recommend_chart
from app.agent.state import AgentDeps, AgentState


def chart_edit(state: AgentState, deps: AgentDeps) -> dict:
    result, spec = state["previous_result"], state.get("previous_spec")
    return {"spec": spec, "result": result, "chart_spec": recommend_chart(result, spec, state.get("chart_type"))}
