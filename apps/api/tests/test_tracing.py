"""Run tracing: OpenTelemetry trace ids, run rows and LLM request metadata."""

from dataclasses import replace
import json
import re

from agent_fixtures import GOOD_SQL, deps, extraction_reply, routing_reply
from fakes import FakeLogWriter, FakeRunner
import httpx
import pytest

from app.agent.graph import run_question
from app.agent.state import RunCancelled
from app.data.clickhouse import QueryError
from app.llm.client import LiteLLMClient, Prompt
from app.llm.embeddings import LiteLLMEmbeddings
from app.observability.tracing import current_run, node_span, run_span, trusted_pack_calls

QUESTION = "Top 10 best-selling widgets in Q1 2024 compared with Q1 2025"


def logged(llm_replies, runner=None, logs=None):
    return replace(deps(llm_replies, runner), logs=logs or FakeLogWriter(), user_id="tester")


def test_trace_id_is_the_32_hex_opentelemetry_trace_id():
    agent = deps([routing_reply(), extraction_reply(), GOOD_SQL, "Blue led."])
    state = run_question(QUESTION, agent)
    assert re.fullmatch(r"[0-9a-f]{32}", state["trace_id"])
    assert all(call[2] == state["trace_id"] for call in agent.runner.calls)


def test_each_run_gets_its_own_trace_id():
    first = run_question(QUESTION, deps([routing_reply(), extraction_reply(), GOOD_SQL, "Blue led."]))
    second = run_question(QUESTION, deps([routing_reply(), extraction_reply(), GOOD_SQL, "Blue led."]))
    assert first["trace_id"] != second["trace_id"]


def test_run_rows_bracket_the_graph():
    agent = logged([routing_reply(), extraction_reply(), GOOD_SQL, "Blue led."])
    state = run_question(QUESTION, agent)
    running, final = agent.logs.runs()
    assert (running.status, final.status) == ("running", "succeeded")
    assert running.trace_id == final.trace_id == state["trace_id"]
    assert (final.user_id, final.pack, final.question, final.intent) == ("tester", "minimal", QUESTION, "data_query")
    assert final.log_complete is True and final.lost_records == 0
    assert final.updated_at >= running.updated_at and final.ts == running.ts
    assert agent.logs.flushed == [state["trace_id"]]


def test_failed_running_row_marks_the_log_incomplete_but_answers():
    agent = logged([routing_reply(), extraction_reply(), GOOD_SQL, "Blue led."], logs=FakeLogWriter(write_results=[False]))
    state = run_question(QUESTION, agent)
    assert state["summary"] == "Blue led."
    assert agent.logs.runs()[-1].log_complete is False


def test_lost_records_mark_the_log_incomplete():
    agent = logged([routing_reply(), extraction_reply(), GOOD_SQL, "Blue led."], logs=FakeLogWriter(lost=2))
    run_question(QUESTION, agent)
    final = agent.logs.runs()[-1]
    assert (final.log_complete, final.lost_records) == (False, 2)


def test_an_out_of_scope_run_records_its_intent_and_success():
    agent = logged([routing_reply("out_of_scope"), "I answer data questions."])

    run_question("Write me a poem", agent)

    final = agent.logs.runs()[-1]
    assert (final.status, final.intent, final.error) == ("succeeded", "out_of_scope", "")


def test_rejected_and_failed_runs_record_their_status():
    rejected = logged([routing_reply(), extraction_reply(filters=[{"column_term": None, "op": "=", "values": ["Mars"]}])])
    run_question("Widgets on Mars?", rejected)
    final = rejected.logs.runs()[-1]
    assert final.status == "rejected" and "Mars" in final.error

    clarified = logged([routing_reply(), extraction_reply(rank_term=None)])
    run_question("Which widgets?", clarified)
    final = clarified.logs.runs()[-1]
    assert (final.status, final.intent, final.error) == ("clarified", "data_query", "")

    failed = logged([routing_reply(), extraction_reply(), "SELECT secret FROM marts.widget_sales"])
    run_question(QUESTION, failed)
    final = failed.logs.runs()[-1]
    assert final.status == "failed" and "policy" in final.error


def test_graph_exception_still_writes_the_final_row():
    agent = logged([routing_reply(), extraction_reply(), GOOD_SQL], runner=FakeRunner(runs=[RuntimeError("driver crashed")]))
    with pytest.raises(RuntimeError, match="driver crashed"):
        run_question(QUESTION, agent)
    final = agent.logs.runs()[-1]
    assert final.status == "error" and "RuntimeError: driver crashed" in final.error


def test_a_cancelled_run_stops_before_its_next_node_and_records_it():
    seen = []

    def progress(name, phase, state, update):
        seen.append((name, phase))
        if name == "retrieve":
            raise RunCancelled()

    agent = replace(logged([routing_reply(), extraction_reply(), GOOD_SQL, "Blue led."]), progress=progress)
    with pytest.raises(RunCancelled):
        run_question(QUESTION, agent)

    assert seen[-1] == ("retrieve", "start")
    assert agent.llm.calls[-1].tier == "fast" and len(agent.llm.calls) == 2
    final = agent.logs.runs()[-1]
    assert final.status == "cancelled"


def test_llm_calls_carry_the_trace_and_node_and_are_counted():
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        sent.append(body)
        if request.url.path.endswith("/embeddings"):
            return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.0, 0.0]}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    transport = httpx.MockTransport(handler)
    llm = LiteLLMClient("http://litellm:4000", "sk-test", http=httpx.Client(transport=transport))
    embeddings = LiteLLMEmbeddings("http://litellm:4000", "sk-test", 2, http=httpx.Client(transport=transport))

    prompt = Prompt(system="rules", user="question")
    llm.text("fast", prompt)
    with trusted_pack_calls():
        embeddings.embed(["pack text"])
    with run_span() as run:
        llm.text("fast", prompt)
        run.screening = "flag"
        with node_span("extract"):
            llm.text("fast", prompt)
            embeddings.embed(["text"])
        llm.text("fast", prompt)
        assert run.llm_calls == 4
    assert current_run() is None

    # Outside a run and outside trusted pack calls nothing marks the request as screened; the gateway rejects it.
    assert sent[0]["metadata"] == {"tier": "fast"}
    assert sent[1]["metadata"] == {"screening": "trusted_pack", "tier": "embed"}
    assert sent[2]["metadata"] == {"trace_id": run.trace_id, "node": "", "tier": "fast"}
    assert sent[3]["metadata"] == {"trace_id": run.trace_id, "node": "extract", "screening": "flag", "tier": "fast"}
    assert sent[4]["metadata"] == {"trace_id": run.trace_id, "node": "extract", "screening": "flag", "tier": "embed"}
    assert sent[5]["metadata"] == {"trace_id": run.trace_id, "node": "", "screening": "flag", "tier": "fast"}
