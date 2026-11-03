"""The agent's LangGraph flow (DECISIONS §6, without the chart recommender).

load_context -> router, then out_of_scope -> end for an out-of-scope
question and, for every other intent so far, the data_query flow:
extract -> resolve_time -> retrieve -> build_spec -> gate -> generate_sql ->
guard -> explain -> execute -> check, where check loops back to generate_sql
for repairable errors, stops on policy errors or exhausted retries, and
otherwise continues to shape_result -> summarize. A node that sets
``rejection``, or the gate's ``denial``, ends the run before any SQL is
generated.
"""

from collections.abc import Callable
from dataclasses import replace
from functools import partial

from langgraph.graph import END, START, StateGraph

from app.agent.nodes.build_spec import build_spec
from app.agent.nodes.check import check, route
from app.agent.nodes.execute import execute_node
from app.agent.nodes.explain import explain_node
from app.agent.nodes.extract import extract
from app.agent.nodes.gate import gate
from app.agent.nodes.generate_sql import generate_sql
from app.agent.nodes.guard import guard
from app.agent.nodes.load_context import load_context
from app.agent.nodes.out_of_scope import out_of_scope
from app.agent.nodes.resolve_time import resolve_time
from app.agent.nodes.retrieve import retrieve
from app.agent.nodes.router import router
from app.agent.nodes.shape_result import shape_result
from app.agent.nodes.summarize import summarize
from app.agent.state import AgentDeps, AgentState, RunCancelled
from app.observability.instrument import LoggingRunner, instrument
from app.observability.runs import RunLog
from app.observability.tracing import run_span

# Four generations of five nodes each plus the fixed nodes stay well inside this.
RECURSION_LIMIT = 60


def _unless_rejected(next_node: str) -> Callable[[AgentState], str]:
    return lambda state: END if state.get("rejection") else next_node


def _unless_denied(next_node: str) -> Callable[[AgentState], str]:
    return lambda state: END if state.get("denial") else next_node


def _unless_failed(next_node: str) -> Callable[[AgentState], str]:
    """Skip to check when the current attempt already failed."""
    return lambda state: "check" if state["attempts"][-1].error is not None else next_node


def build_graph(deps: AgentDeps):
    graph = StateGraph(AgentState)
    nodes = {
        "load_context": load_context, "router": router, "out_of_scope": out_of_scope,
        "extract": extract, "resolve_time": resolve_time, "retrieve": retrieve, "build_spec": build_spec, "gate": gate,
        "generate_sql": generate_sql, "guard": guard, "explain": explain_node, "execute": execute_node,
        "check": check, "shape_result": shape_result, "summarize": summarize,
    }
    for name, node in nodes.items():
        graph.add_node(name, partial(instrument(name, node), deps=deps))

    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "router")
    graph.add_conditional_edges(
        "router", lambda state: "out_of_scope" if state["intent"] == "out_of_scope" else "extract",
        ["out_of_scope", "extract"],
    )
    graph.add_edge("out_of_scope", END)
    graph.add_conditional_edges("extract", _unless_rejected("resolve_time"), ["resolve_time", END])
    graph.add_conditional_edges("resolve_time", _unless_rejected("retrieve"), ["retrieve", END])
    graph.add_conditional_edges("retrieve", _unless_rejected("build_spec"), ["build_spec", END])
    graph.add_conditional_edges("build_spec", _unless_rejected("gate"), ["gate", END])
    graph.add_conditional_edges("gate", _unless_denied("generate_sql"), ["generate_sql", END])
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


def _outcome(state: AgentState) -> tuple[str, str, str]:
    """Status, intent and error of a finished run for its ``runs`` row."""
    intent = state.get("intent", "")
    if state.get("rejection"):
        return "rejected", intent, state["rejection"]
    if state.get("denial"):
        return "denied", intent, state["denial"].message
    if state.get("result") is not None or state.get("reply") is not None:
        return "succeeded", intent, ""
    errors = state.get("errors", [])
    return "failed", intent, str(errors[-1]) if errors else ""


def run_question(question: str, deps: AgentDeps) -> AgentState:
    """Run one question under its own trace; with ``deps.logs`` its run row brackets the graph.

    A ``RunCancelled`` raised by ``deps.progress`` ends the run as ``cancelled`` and propagates.
    """
    with run_span() as run:
        initial: AgentState = {
            "question": question,
            "trace_id": run.trace_id,
            "attempts": [],
            "errors": [],
            "warnings": [],
        }
        config = {"recursion_limit": RECURSION_LIMIT}
        if deps.logs is None:
            return build_graph(deps).invoke(initial, config=config)
        log = RunLog(deps.logs, run, user_id=deps.user_id, pack=deps.compiled.pack.name, question=question)
        deps = replace(deps, runner=LoggingRunner(deps.runner, deps.logs))
        try:
            state = build_graph(deps).invoke(initial, config=config)
        except RunCancelled:
            log.finish("cancelled", intent="", error="the client stopped the run")
            raise
        except Exception as error:
            log.finish("error", intent="", error=f"{type(error).__name__}: {error}")
            raise
        status, intent, error = _outcome(state)
        log.finish(status, intent=intent, error=error)
        return state
