"""Redraw the previous answer (DECISIONS §6 step 3).

A chart edit reuses the QuerySpec and shaped Result stored with the previous
turn and asks the chart recommender for the type the router read from the
question. It never generates or runs SQL and calls no LLM; the graph sends a
chart edit without a previous result through the data question flow instead.
"""

from app.agent.chart_recommender import recommend_chart
from app.agent.state import AgentDeps, AgentState


def chart_edit(state: AgentState, deps: AgentDeps) -> dict:
    result = state["previous_result"]
    return {
        "spec": state.get("previous_spec"),
        "result": result,
        "chart_spec": recommend_chart(result, state.get("chart_type")),
    }
