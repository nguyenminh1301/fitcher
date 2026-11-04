"""load_context and router with fake conversation history and a fake LLM (DECISIONS §6 steps 1-3)."""

from dataclasses import replace

from agent_fixtures import GOOD_SQL, deps, extraction_reply, routing_reply
import pytest
from test_contracts import spec

from app.agent.graph import run_question
from app.agent.nodes.extract import extract
from app.agent.nodes.load_context import CONTEXT_TURNS, load_context
from app.agent.nodes.out_of_scope import FALLBACK, out_of_scope
from app.agent.nodes.resolve_time import resolve_time
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

    assert update == {"intent": "metadata_qa", "intent_fallback": False, "language": "vi", "chart_type": None}
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

    assert update == {"intent": "data_query", "intent_fallback": True, "language": None, "chart_type": None}


def test_a_routed_question_records_its_intent_on_the_run():
    agent = deps([routing_reply(), extraction_reply(), GOOD_SQL, "Done."])

    state = run_question("Top 10 best-selling widgets in Q1 2024 compared with Q1 2025", agent)

    assert state["intent"] == "data_query"
    assert [call.alias for call in agent.llm.calls] == ["fast", "fast", "sql-gen", "fast"]


def test_a_fallback_routing_with_an_unreadable_question_clarifies_before_sql():
    agent = deps([LLMError("alias fast returned HTTP 500"), extraction_reply(rank_term=None)])

    state = run_question("Which widgets?", agent)

    assert state["intent_fallback"] is True
    assert state["clarification"].question == "Which measure should I report?"
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

    assert seen == ["screen", "load_context", "router", "out_of_scope"]
    assert state["reply"] == "I answer questions about the shop's data."
    assert [call.alias for call in agent.llm.calls] == ["fast", "fast"]
    assert agent.runner.calls == []


FOLLOW_UP = "What about last year?"


def test_extract_prompt_shows_recent_turns_and_previous_spec_only_with_history():
    first = deps([extraction_reply()])
    extract({"question": "Top widgets in Q1 2025", "history": [], "previous_spec": None}, first)
    follow = deps([extraction_reply(periods=[], previous_periods={"unit": "year", "offset": -1})])
    state = {"question": FOLLOW_UP, "history": [turn(1, query_spec=spec(), result=RESULT)], "previous_spec": spec()}

    update = extract(state, follow)

    assert "Earlier turns" not in first.llm.calls[0].prompt
    prompt = follow.llm.calls[0].prompt
    assert "Earlier turns" in prompt and "question 1" in prompt and "answer 1" in prompt
    assert '"Q1 2025"' in prompt and "Blue secret row" not in prompt
    # The instruction to combine a reply with the question it answers sits right before the question.
    assert prompt.index("the message is that choice") > prompt.index("Earlier turns")
    assert prompt.index("the message is that choice") < prompt.index("<question>")
    assert update["extraction"].previous_periods.offset == -1
    assert "rejection" not in update


def test_a_follow_up_without_a_previous_query_has_no_period():
    extraction = extract({"question": FOLLOW_UP}, deps([extraction_reply(periods=[], previous_periods={"unit": "year", "offset": -1})]))["extraction"]

    update = resolve_time({"extraction": extraction, "previous_spec": None}, deps([]))

    assert update == {"periods": []}


def test_what_about_last_year_reuses_the_previous_question():
    question = "Top 10 best-selling widgets in Q1 2024 compared with Q1 2025"
    first = run_question(question, deps([routing_reply(), extraction_reply(), GOOD_SQL, "Widget 0 led."]))
    previous = Turn(turn=1, revision=1, question=question, answer="Widget 0 led.", query_spec=first["spec"], result=first["result"])
    follow_up = extraction_reply(periods=[], previous_periods={"unit": "year", "offset": -1})
    agent = replace(deps([routing_reply(), follow_up, GOOD_SQL, "Widget 1 led."]), history=(previous,))

    state = run_question(FOLLOW_UP, agent)

    spec_now, spec_before = state["spec"], first["spec"]
    assert [(p.label, p.start.isoformat(), p.end.isoformat()) for p in spec_now.periods] == [
        ("Q1 2023", "2023-01-01", "2023-04-01"), ("Q1 2024", "2024-01-01", "2024-04-01"),
    ]
    assert (spec_now.metric_ids, spec_now.dimensions, spec_now.top_n, spec_now.compare, spec_now.rank_by) == (
        spec_before.metric_ids, spec_before.dimensions, spec_before.top_n, spec_before.compare, spec_before.rank_by,
    )
    assert spec_now.rank_period == "Q1 2024"
    assert state["result"] is not None
