"""chart_edit: redraw the previous answer from its stored result, never generating or running SQL."""

from dataclasses import replace

from agent_fixtures import GOOD_SQL, deps, extraction_reply, routing_reply
import pytest

from app.agent.chart_rules import recommend_chart
from app.agent.graph import run_question
from app.agent.nodes.chart_edit import chart_edit
from app.agent.nodes.router import router
from app.conversation.store import Turn

QUESTION = "Top 10 best-selling widgets in Q1 2024 compared with Q1 2025"


def previous_turn() -> Turn:
    state = run_question(QUESTION, deps([routing_reply(), extraction_reply(), GOOD_SQL, "Widget 0 led."]))
    return Turn(turn=1, revision=1, question=QUESTION, answer="Widget 0 led.", query_spec=state["spec"], result=state["result"])


def started(agent):
    seen = []
    return replace(agent, progress=lambda name, phase, state, update: seen.append(name) if phase == "start" else None), seen


def test_the_router_returns_the_chart_type_asked_for():
    update = router({"question": "Draw it as a line", "history": [], "previous_spec": None}, deps([routing_reply("chart_edit", chart_type="line")]))

    assert (update["intent"], update["chart_type"]) == ("chart_edit", "line")


def test_the_router_prompt_lists_the_chart_types():
    agent = deps([routing_reply()])

    router({"question": "q", "history": [], "previous_spec": None}, agent)

    assert "`chart_type`" in agent.llm.calls[0].prompt and "grouped_bar" in agent.llm.calls[0].prompt


@pytest.mark.parametrize(("requested", "drawn"), [("table", "table"), ("pie", "bar"), ("line", "bar"), (None, "bar")])
def test_chart_edit_draws_the_type_asked_for_when_the_rules_allow_it(requested, drawn):
    turn = previous_turn()

    update = chart_edit({"previous_spec": turn.query_spec, "previous_result": turn.result, "chart_type": requested}, deps([]))

    assert update["chart_spec"].type == drawn


def test_chart_edit_reuses_the_previous_spec_and_result():
    turn = previous_turn()

    update = chart_edit({"previous_spec": turn.query_spec, "previous_result": turn.result, "chart_type": "line"}, deps([]))

    assert (update["spec"], update["result"], update["chart_spec"]) == (turn.query_spec, turn.result, recommend_chart(turn.result, turn.query_spec, "line"))


def test_draw_it_as_a_line_runs_no_sql_node():
    agent, seen = started(replace(deps([routing_reply("chart_edit", chart_type="line")]), history=(previous_turn(),)))

    state = run_question("Draw it as a line", agent)

    assert seen == ["load_context", "router", "chart_edit"]
    assert not {"generate_sql", "guard", "explain", "execute"} & set(seen)
    assert agent.runner.calls == [] and [call.alias for call in agent.llm.calls] == ["fast"]
    assert state["result"] == previous_turn().result and state.get("attempts") == []


def test_a_chart_edit_without_a_previous_result_takes_the_data_flow():
    agent, seen = started(deps([routing_reply("chart_edit", chart_type="line"), extraction_reply(rank_term=None)]))

    state = run_question("Draw it as a line", agent)

    assert "extract" in seen and "chart_edit" not in seen
    assert state["clarification"] is not None
