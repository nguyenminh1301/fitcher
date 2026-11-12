"""Node events and SQL attempts written for a logged run."""

from dataclasses import replace
from datetime import date
import json

from agent_fixtures import GOOD_SQL, deps, extraction_reply, good_output, routing_reply
from fakes import FakeLogWriter, FakeRunner
from pydantic import BaseModel
import pytest

from app.agent.graph import run_question
from app.data.clickhouse import QueryError
from app.observability.instrument import PAYLOAD_LIMIT, payload_json

QUESTION = "Top 10 best-selling widgets in Q1 2024 compared with Q1 2025"
NODES = [
    "screen", "load_context", "router", "extract", "resolve_time", "retrieve", "build_spec", "gate", "generate_sql", "guard", "explain", "execute", "check",
    "shape_result", "chart_recommender", "summarize",
]


def logged(llm_replies, runner=None):
    return replace(deps(llm_replies, runner), logs=FakeLogWriter())


def queued(agent, table):
    return [record for record in agent.logs.queued if record.TABLE == table]


def test_each_node_writes_one_event():
    agent = logged([routing_reply(), extraction_reply(), GOOD_SQL, "Blue led."])
    state = run_question(QUESTION, agent)
    events = queued(agent, "events")
    assert [event.node for event in events] == NODES
    assert all(event.status == "ok" and event.trace_id == state["trace_id"] for event in events)
    assert all(event.ts <= event.ended_at for event in events)
    summary = json.loads(events[-1].payload)
    assert summary == {"summary": "Blue led."}


def test_result_rows_are_logged_as_counts_only():
    agent = logged([routing_reply(), extraction_reply(), GOOD_SQL, "Blue led."])
    run_question(QUESTION, agent)
    execute, shape = (event for event in queued(agent, "events") if event.node in ("execute", "shape_result"))
    assert "Widget 0" not in execute.payload and "Widget 0" not in shape.payload
    assert json.loads(execute.payload)["output"]["row_count"] == 7
    assert json.loads(shape.payload)["result"]["row_count"] == 7


def test_a_node_that_raises_writes_an_error_event():
    agent = logged([routing_reply(), extraction_reply(), GOOD_SQL], FakeRunner(runs=[RuntimeError("driver crashed")]))
    with pytest.raises(RuntimeError):
        run_question(QUESTION, agent)
    last = queued(agent, "events")[-1]
    assert (last.node, last.status) == ("execute", "error")
    assert "RuntimeError: driver crashed" in last.payload


def test_every_execution_writes_a_sql_run():
    failure = QueryError("runtime", "Code: 159. Timeout exceeded", "qid-slow", 159)
    agent = logged(
        [routing_reply(), extraction_reply(), GOOD_SQL, GOOD_SQL, "Blue led."], FakeRunner(runs=[failure, good_output()])
    )
    state = run_question(QUESTION, agent)
    first, second = queued(agent, "sql_runs")
    assert (first.attempt, first.query_id, first.rows, first.sql) == (1, "qid-slow", 0, GOOD_SQL)
    assert first.error == "runtime: Code: 159. Timeout exceeded"
    assert (second.attempt, second.query_id, second.rows, second.error) == (2, "qid-ok", 7, "")
    assert first.trace_id == second.trace_id == state["trace_id"]


class Item(BaseModel):
    day: date
    note: str


def test_payload_serializes_models_dates_and_unknown_values():
    text, truncated = payload_json({"item": Item(day=date(2025, 1, 1), note="x"), "when": date(2024, 4, 1), "other": object})
    data = json.loads(text)
    assert truncated is False
    assert data["item"] == {"day": "2025-01-01", "note": "x"}
    assert data["when"] == "2024-04-01"
    assert "object" in data["other"]


def test_large_payload_is_cut_at_the_limit_on_a_character_boundary():
    text, truncated = payload_json({"summary": "doanh thu tăng " * 4000})
    assert truncated is True
    assert len(text.encode("utf-8")) <= PAYLOAD_LIMIT
    assert text.startswith('{"summary": "doanh thu tăng')
