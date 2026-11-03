"""POST /ask: authentication, rate limiting and the order of its server-sent events (DECISIONS §6)."""

import asyncio
from dataclasses import dataclass, field, replace
import json
import threading
import time

from agent_fixtures import GOOD_SQL, compiled_fixture, deps, extraction_reply, good_output, routing_reply
from auth_fixtures import token, verifier
from fakes import FakeRunner
from fastapi.testclient import TestClient
import pytest

from app.agent.state import RunCancelled
from app.api import runtime
from app.api.agent import GraphRun, QueryIds
from app.api.ask import AnswerEvents, event_stream
from app.api.rate_limit import RateLimiter
from app.contracts.events import AskEvent
from app.data.clickhouse import QueryError, QueryStopper
from app.main import app

QUESTION = "Top 10 best-selling widgets in Q1 2024 compared with Q1 2025"


def sql_error() -> QueryError:
    return QueryError("sql", "Code: 47. DB::Exception: Unknown identifier", "qid-bad", 47)


@dataclass
class FakeAgent:
    """Starts real graph runs over fake LLM, search and ClickHouse clients."""

    llm_replies: list
    runner: FakeRunner | None = None
    compiled: object = None
    started: list = field(default_factory=list)

    def start(self, *, role, user_id, today):
        self.started.append((role, user_id, today))
        agent_deps = deps(self.llm_replies, self.runner)
        return GraphRun(replace(agent_deps, compiled=self.compiled or agent_deps.compiled, role=role, user_id=user_id))


def pack_with_refunds_clerk():
    """The fixture pack plus a role that may read refunds only."""
    compiled = compiled_fixture()
    viewer = compiled.pack.policies.roles[0]
    clerk = viewer.model_copy(update={"id": "refunds_clerk", "datasets": [viewer.datasets[1]]})
    policies = compiled.pack.policies.model_copy(update={"roles": [viewer, clerk]})
    return compiled.model_copy(update={"pack": compiled.pack.model_copy(update={"policies": policies})})


def serve(agent: FakeAgent, compiled, per_minute: int = 3):
    limiter = RateLimiter(per_minute)
    app.dependency_overrides[runtime.get_verifier] = lambda: verifier()
    app.dependency_overrides[runtime.get_compiled] = lambda: compiled
    app.dependency_overrides[runtime.get_agent] = lambda: agent
    app.dependency_overrides[runtime.get_rate_limiter] = lambda: limiter


@pytest.fixture
def ask_client():
    agent = FakeAgent([routing_reply(), extraction_reply(), GOOD_SQL, "Widget 0 led."])
    serve(agent, compiled_fixture())
    with TestClient(app) as client:
        client.agent = agent
        yield client
    app.dependency_overrides.clear()


def parse(body: str) -> list[dict]:
    """The SSE frames of a response body, each as its validated event."""
    events = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if not line.startswith(":"))
        if not lines:
            continue
        data = json.loads(lines["data"])
        assert lines["event"] == data["event"]
        events.append(AskEvent.model_validate(data).root.model_dump())
    return events


def kinds(events: list[dict]) -> list[str]:
    return [event["event"] for event in events if event["event"] != "status"]


def post(client, question=QUESTION, headers=None, **body):
    return client.post("/ask", json={"question": question, **body}, headers={"Authorization": f"Bearer {token()}", **(headers or {})})


def test_a_data_question_streams_status_sql_result_chart_summary_and_done(ask_client):
    response = post(ask_client, timezone="Asia/Ho_Chi_Minh")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse(response.text)
    assert kinds(events) == ["sql", "result", "chart_spec", "summary", "done"]
    assert events[0] == {"event": "status", "trace_id": events[0]["trace_id"], "node": "load_context", "phase": "start", "attempt": None}
    assert len({event["trace_id"] for event in events}) == 1
    sql = next(event for event in events if event["event"] == "sql")
    assert sql["sql"].startswith(GOOD_SQL) and sql["attempt"] == 1
    chart = next(event for event in events if event["event"] == "chart_spec")["spec"]
    assert chart["type"] == "table" and chart["allowed_types"] == ["table"]
    summary = next(event for event in events if event["event"] == "summary")
    assert (summary["text"], summary["lang"]) == ("Widget 0 led.", "en")
    assert ask_client.agent.started[0][:2] == ("viewer", "lab.viewer")


def test_every_node_streams_a_start_and_an_end_status_in_graph_order(ask_client):
    statuses = [(event["node"], event["phase"]) for event in parse(post(ask_client).text) if event["event"] == "status"]

    nodes = [node for node, phase in statuses if phase == "start"]
    assert nodes == [
        "load_context", "router", "extract", "resolve_time", "retrieve", "build_spec", "gate", "generate_sql", "guard", "explain", "execute",
        "check", "shape_result", "summarize",
    ]
    assert statuses == [item for node in nodes for item in ((node, "start"), (node, "end"))]


def test_a_repaired_query_streams_each_sql_attempt_before_the_result():
    agent = FakeAgent(
        [routing_reply(), extraction_reply(), "SELECT nope(widget_name) FROM marts.widget_sales", GOOD_SQL, "Done."],
        FakeRunner(explains=[sql_error()], runs=[good_output()]),
    )

    events = collect(agent)

    assert kinds(events) == ["sql", "sql", "result", "chart_spec", "summary", "done"]
    attempts = [event for event in events if event["event"] == "status" and event["node"] == "generate_sql"]
    assert [event["attempt"] for event in attempts] == [1, 1, 2, 2]


def test_a_role_without_permission_receives_a_deny_event():
    compiled = pack_with_refunds_clerk()
    agent = FakeAgent([routing_reply(), extraction_reply()], compiled=compiled)
    serve(agent, compiled)
    clerk = token(realm_access={"roles": ["refunds_clerk"]})
    try:
        with TestClient(app) as client:
            response = client.post("/ask", json={"question": QUESTION}, headers={"Authorization": f"Bearer {clerk}"})
    finally:
        app.dependency_overrides.clear()

    events = parse(response.text)
    assert kinds(events) == ["deny", "done"]
    deny = next(event for event in events if event["event"] == "deny")
    assert deny["role"] == "refunds_clerk"
    assert deny["blocked"] == ["widget_sales"]
    assert "nothing was queried" in deny["message"]
    assert not [event for event in events if event["event"] == "status" and event["node"] == "generate_sql"]


def test_exhausted_retries_end_with_the_last_sql_and_an_error():
    sqls = [f"SELECT widget_name AS w{n} FROM marts.widget_sales" for n in range(4)]
    agent = FakeAgent([routing_reply(), extraction_reply(), *sqls], FakeRunner(explains=[sql_error()] * 4))

    events = collect(agent)

    assert kinds(events) == ["sql", "sql", "sql", "sql", "error"]
    error = events[-1]
    assert error["kind"] == "failed" and error["sql"].startswith(sqls[-1])
    assert [event["attempt"] for event in events if event["event"] == "sql"] == [1, 2, 3, 4]
    assert "Unknown identifier" in error["error"]


def test_a_question_the_flow_cannot_read_asks_for_clarification():
    events = collect(FakeAgent([routing_reply(), extraction_reply(metric_terms=[], rank_term=None)]))

    assert kinds(events) == ["clarify", "done"]
    assert "names no measure" in events[-2]["question"]


class ScriptedRun:
    """A fake graph: reports ``nodes`` through progress, then returns ``state`` or raises ``error``."""

    def __init__(self, nodes=("extract",), state=None, error=None, pause=0.0):
        self.nodes, self.state, self.error, self.pause = nodes, state, error, pause
        self.cancelled = threading.Event()
        self.stopped_by = None

    def run(self, question, progress):
        state = {"trace_id": "a" * 32, "attempts": []}
        try:
            for node in self.nodes:
                progress(node, "start", state, None)
                time.sleep(self.pause)
                progress(node, "end", state, {})
        except RunCancelled as stop:
            self.stopped_by = stop
            raise
        if self.error:
            raise self.error
        return {**state, **(self.state or {})}

    def cancel(self):
        self.cancelled.set()


async def drain(stream) -> list[str]:
    return [chunk async for chunk in stream]


def test_an_internal_error_is_the_last_event_and_hides_its_detail():
    run = ScriptedRun(error=ValueError("secret detail"))

    chunks = asyncio.run(drain(event_stream(run, QUESTION, AnswerEvents("viewer"))))

    events = parse("".join(chunks))
    assert kinds(events) == ["error"]
    assert events[-1]["kind"] == "internal" and "secret" not in events[-1]["message"]
    assert events[-1]["trace_id"] == "a" * 32


def test_nothing_follows_done():
    run = ScriptedRun(state={"result": object()})

    events = parse("".join(asyncio.run(drain(event_stream(run, QUESTION, AnswerEvents("viewer"))))))

    assert kinds(events) == ["done"] and events[-1]["event"] == "done"


def test_a_slow_node_sends_heartbeat_comments():
    run = ScriptedRun(nodes=("execute",), state={"result": object()}, pause=0.25)

    chunks = asyncio.run(drain(event_stream(run, QUESTION, AnswerEvents("viewer"), heartbeat_seconds=0.05)))

    assert ": keep-alive\n\n" in chunks
    assert kinds(parse("".join(chunks))) == ["done"]


def test_a_client_disconnect_stops_the_run_and_kills_its_query():
    run = ScriptedRun(nodes=("execute", "check", "shape_result"), state={"result": object()}, pause=0.2)

    async def first_event_then_disconnect():
        stream = event_stream(run, QUESTION, AnswerEvents("viewer"))
        first = await anext(stream)
        await stream.aclose()
        return first

    first = asyncio.run(first_event_then_disconnect())

    assert first.startswith("event: status")
    assert run.cancelled.wait(2)
    deadline = time.monotonic() + 2
    while run.stopped_by is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert isinstance(run.stopped_by, RunCancelled)


def collect(agent: FakeAgent, role="viewer") -> list[dict]:
    run = agent.start(role=role, user_id="lab.viewer", today=None)
    return parse("".join(asyncio.run(drain(event_stream(run, QUESTION, AnswerEvents(role))))))


def test_a_missing_or_invalid_token_is_unauthorized_before_the_graph_starts(ask_client):
    assert ask_client.post("/ask", json={"question": QUESTION}).status_code == 401
    expired = ask_client.post("/ask", json={"question": QUESTION}, headers={"Authorization": f"Bearer {token(exp=1_000_000)}"})
    assert expired.status_code == 401
    assert ask_client.agent.started == []


def test_a_token_without_a_pack_role_is_forbidden(ask_client):
    response = ask_client.post(
        "/ask", json={"question": QUESTION}, headers={"Authorization": f"Bearer {token(realm_access={'roles': ['admin']})}"},
    )

    assert response.status_code == 403
    assert ask_client.agent.started == []


def test_too_many_questions_are_refused_before_the_graph_starts(ask_client):
    assert [post(ask_client).status_code for _ in range(3)] == [200, 200, 200]

    refused = post(ask_client)

    assert refused.status_code == 429
    assert int(refused.headers["retry-after"]) >= 1
    assert len(ask_client.agent.started) == 3


@pytest.mark.parametrize("body", [{"question": ""}, {"question": QUESTION, "timezone": "Mars/Base"}, {"question": QUESTION, "extra": 1}])
def test_an_invalid_request_is_unprocessable(ask_client, body):
    response = ask_client.post("/ask", json=body, headers={"Authorization": f"Bearer {token()}"})

    assert response.status_code == 422
    assert ask_client.agent.started == []


def test_a_cancelled_run_stops_its_latest_query_as_its_role_user():
    class Client:
        def __init__(self):
            self.commands = []

        def command(self, sql, parameters=None):
            self.commands.append((sql, parameters))

    client, ids = Client(), QueryIds()
    run = GraphRun(deps([]), ids, lambda: (QueryStopper(client), "agent_viewer"))

    run.cancel()
    assert client.commands == []
    ids()
    run.cancel()

    assert client.commands == [(
        "KILL QUERY WHERE query_id = {query_id:String} AND user = {user:String} ASYNC",
        {"query_id": ids.latest, "user": "agent_viewer"},
    )]


def test_a_failed_stop_is_logged_and_never_raised(caplog):
    def broken():
        raise RuntimeError("CLICKHOUSE_QUERY_STOPPER_PASSWORD must be set")

    ids = QueryIds()
    ids()

    GraphRun(deps([]), ids, broken).cancel()

    assert "could not stop query" in caplog.text
