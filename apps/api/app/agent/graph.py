"""The ``data_query`` LangGraph flow (DECISIONS §6 steps 4-16, without router, gate and charts).

extract -> resolve_time -> retrieve -> build_spec -> generate_sql -> guard ->
explain -> execute -> check, where check loops back to generate_sql for
repairable errors, stops on policy errors or exhausted retries, and otherwise
continues to shape_result -> summarize. A node that sets ``rejection`` ends
the run before any SQL is generated.
"""

from collections.abc import Callable
from functools import partial
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from app.agent.nodes.build_spec import build_spec
from app.agent.nodes.check import check, route
from app.agent.nodes.execute import execute_node
from app.agent.nodes.explain import explain_node
from app.agent.nodes.extract import extract
from app.agent.nodes.generate_sql import generate_sql
from app.agent.nodes.guard import guard
from app.agent.nodes.resolve_time import resolve_time
from app.agent.nodes.retrieve import retrieve
from app.agent.nodes.shape_result import shape_result
from app.agent.nodes.summarize import summarize
from app.agent.state import AgentDeps, AgentState

# Four generations of five nodes each plus the fixed nodes stay well inside this.
RECURSION_LIMIT = 60


def _unless_rejected(next_node: str) -> Callable[[AgentState], str]:
    return lambda state: END if state.get("rejection") else next_node


def _unless_failed(next_node: str) -> Callable[[AgentState], str]:
    """Skip to check when the current attempt already failed."""
    return lambda state: "check" if state["attempts"][-1].error is not None else next_node


def build_graph(deps: AgentDeps):
    graph = StateGraph(AgentState)
    nodes = {
        "extract": extract, "resolve_time": resolve_time, "retrieve": retrieve, "build_spec": build_spec,
        "generate_sql": generate_sql, "guard": guard, "explain": explain_node, "execute": execute_node,
        "check": check, "shape_result": shape_result, "summarize": summarize,
    }
    for name, node in nodes.items():
        graph.add_node(name, partial(node, deps=deps))

    graph.add_edge(START, "extract")
    graph.add_conditional_edges("extract", _unless_rejected("resolve_time"), ["resolve_time", END])
    graph.add_conditional_edges("resolve_time", _unless_rejected("retrieve"), ["retrieve", END])
    graph.add_edge("retrieve", "build_spec")
    graph.add_conditional_edges("build_spec", _unless_rejected("generate_sql"), ["generate_sql", END])
    graph.add_conditional_edges("generate_sql", _unless_failed("guard"), ["guard", "check"])
    graph.add_conditional_edges("guard", _unless_failed("explain"), ["explain", "check"])
    graph.add_conditional_edges("explain", _unless_failed("execute"), ["execute", "check"])
    graph.add_edge("execute", "check")
    graph.add_conditional_edges(
        "check", route, {"retry": "generate_sql", "shape": "shape_result", "stop": END}
    )
    graph.add_edge("shape_result", "summarize")
    graph.add_edge("summarize", END)
    return graph.compile()


def run_question(question: str, deps: AgentDeps, trace_id: str | None = None) -> AgentState:
    initial: AgentState = {
        "question": question,
        "trace_id": trace_id or str(uuid4()),
        "profile": deps.compiled.pack.business_profile,
        "attempts": [],
        "errors": [],
        "warnings": [],
    }
    return build_graph(deps).invoke(initial, config={"recursion_limit": RECURSION_LIMIT})
