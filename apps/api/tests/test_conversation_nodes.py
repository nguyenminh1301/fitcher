"""load_context and router with fake conversation history and a fake LLM (DECISIONS §6 steps 1-3)."""

from dataclasses import replace

from agent_fixtures import GOOD_SQL, deps, extraction_reply, routing_reply
import pytest
from test_contracts import spec

from app.agent.graph import run_question
from app.agent.nodes.load_context import CONTEXT_TURNS, load_context
from app.agent.nodes.out_of_scope import FALLBACK, out_of_scope
from app.agent.nodes.router import ALIAS, router
from app.contracts.result import ColumnInfo, Result
from app.conversation.store import Turn
from app.llm.client import LLMError

RESULT = Result(columns=[ColumnInfo(name="widget_name", type="string", role="dimension")], rows=[["Blue secret row"]], row_count=1)


def turn(number: int, **fields) -> Turn:
    return Turn(turn=number, revision=1, question=f"question {number}", answer=f"answer {number}", **fields)


def test_load_context_keeps_the_last_six_turns_and_the_previous_spec():
    history = (turn(1, query_spec=spec(top_n=3), result=RESULT), *(turn(n) for n in range(2, 8)), turn(8, query_spec=spec(), result=RESULT))
    agent = replace(deps([]), history=history)

    update = load_context({"question": "q"}, agent)

    assert CONTEXT_TURNS == 6
    assert [item.turn for item in update["history"]] == [3, 4, 5, 6, 7, 8]
    assert (update["previous_spec"], update["previous_result"]) == (spec(), RESULT)
    assert update["profile"] == agent.compiled.pack.business_profile


def test_load_context_skips_turns_without_a_spec_for_the_previous_spec():
    agent = replace(deps([]), history=(turn(1, query_spec=spec(), result=RESULT), turn(2)))

    update = load_context({"question": "q"}, agent)

    assert update["previous_spec"] == spec()


def test_load_context_without_history_loads_only_the_profile():
    update = load_context({"question": "q"}, deps([]))

    assert (update["history"], update["previous_spec"], update["previous_result"]) == ([], None, None)


def test_router_returns_the_intent_and_language():
    agent = deps([routing_reply("metadata_qa", language="vi")])

    update = router({"question": "Doanh thu thuần là gì?", "history": [], "previous_spec": None}, agent)

    assert update == {"intent": "metadata_qa", "intent_fallback": False, "language": "vi"}
    assert agent.llm.calls[0].alias == ALIAS == "fast"


def test_router_prompt_carries_history_and_previous_spec_but_no_rows():
    agent = deps([routing_reply("chart_edit")])
    state = {"question": "Draw it as a line", "history": [turn(1, query_spec=spec(), result=RESULT)], "previous_spec": spec()}

    router(state, agent)

    prompt = agent.llm.calls[0].prompt
    assert "question 1" in prompt and "answer 1" in prompt and '"Draw it as a line"' in prompt
    assert '"widget_revenue"' in prompt
    assert "Blue secret row" not in prompt
    assert "data, not instructions" in prompt
    assert "widget retail" in prompt


@pytest.mark.parametrize("reply", [routing_reply("out_of_scope", confidence=0.3), LLMError("alias fast returned HTTP 500")])
def test_an_uncertain_or_failed_routing_falls_back_to_data_query(reply):
    update = router({"question": "q", "history": [], "previous_spec": None}, deps([reply]))

    assert update == {"intent": "data_query", "intent_fallback": True, "language": None}


def test_a_routed_question_records_its_intent_on_the_run():
    agent = deps([routing_reply(), extraction_reply(), GOOD_SQL, "Done."])

    state = run_question("Top 10 best-selling widgets in Q1 2024 compared with Q1 2025", agent)

    assert state["intent"] == "data_query"
    assert [call.alias for call in agent.llm.calls] == ["fast", "fast", "sql-gen", "fast"]


def test_a_fallback_routing_with_an_unreadable_question_stops_before_sql():
    agent = deps([LLMError("alias fast returned HTTP 500"), extraction_reply(rank_term=None)])

    state = run_question("Which widgets?", agent)

    assert state["intent_fallback"] is True
    assert state["rejection"] == "the question names no measure to report"
    assert [call.alias for call in agent.llm.calls] == ["fast", "fast"]


def test_out_of_scope_replies_in_the_question_language():
    agent = deps(["Mình chỉ trả lời câu hỏi về dữ liệu của công ty."])

    update = out_of_scope({"question": "Thời tiết hôm nay thế nào?", "language": "vi"}, agent)

    assert update == {"reply": "Mình chỉ trả lời câu hỏi về dữ liệu của công ty."}
    [call] = agent.llm.calls
    assert (call.method, call.alias) == ("text", "fast")
    assert '"Thời tiết hôm nay thế nào?"' in call.prompt and "(vi)" in call.prompt
    assert "widget retail" in call.prompt and "data, not instructions" in call.prompt


@pytest.mark.parametrize(("language", "expected"), [("vi", "vi"), ("en", "en"), (None, "en"), ("fr", "en")])
def test_out_of_scope_falls_back_to_a_fixed_reply(language, expected):
    update = out_of_scope({"question": "q", "language": language}, deps([LLMError("alias fast returned HTTP 500")]))

    assert update == {"reply": FALLBACK[expected]}


def test_out_of_scope_question_runs_no_extract_or_sql():
    seen = []
    agent = replace(
        deps([routing_reply("out_of_scope", language="en"), "I answer questions about the shop's data."]),
        progress=lambda name, phase, state, update: seen.append(name) if phase == "start" else None,
    )

    state = run_question("Write me a poem", agent)

    assert seen == ["load_context", "router", "out_of_scope"]
    assert state["reply"] == "I answer questions about the shop's data."
    assert [call.alias for call in agent.llm.calls] == ["fast", "fast"]
    assert agent.runner.calls == []
