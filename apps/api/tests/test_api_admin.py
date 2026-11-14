"""The admin sections' endpoints over AdminLogs with a scripted query function."""

from datetime import UTC, date, datetime
import re

from fastapi.testclient import TestClient
import pytest

from agent_fixtures import compiled_fixture
from session_fixtures import SessionHeaders

from app.admin.logs import PAGE_SIZE, AdminLogs
from app.api import runtime
from app.main import app

TS = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)
ADMIN = SessionHeaders(['admin'])
REVIEWER = SessionHeaders(['pack_reviewer'])
RUN = ("t1", TS, "lab.analyst", "viewer", "Revenue by widget", "data_query", "succeeded", 1200, 0.0042, "")


class Script:
    """Answers each query from the first pattern that matches it; records SQL and parameters."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def __call__(self, sql, parameters):
        self.calls.append((sql, parameters))
        for pattern, rows in self.answers:
            if re.search(pattern, sql, re.S):
                return rows
        return []


def logs(answers) -> tuple[AdminLogs, Script]:
    script = Script(answers)
    return AdminLogs(script, "minimal"), script


@pytest.fixture
def client():
    app.dependency_overrides[runtime.get_compiled] = lambda: compiled_fixture()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def use(reader: AdminLogs):
    app.dependency_overrides[runtime.get_admin_logs] = lambda: reader


def test_runs_are_filtered_paged_and_scoped_to_the_pack(client):
    reader, script = logs([(r"FROM agent_logs\.runs", [RUN])])
    use(reader)

    response = client.get("/admin/runs", headers=ADMIN,
                          params={"user": "lab.analyst", "status": "succeeded", "from": "2026-11-01", "to": "2026-11-06", "page": 2})

    assert response.status_code == 200
    assert response.json()[0] == {
        "trace_id": "t1", "ts": "2026-11-05T09:00:00Z", "user_id": "lab.analyst", "role": "viewer",
        "question": "Revenue by widget", "intent": "data_query", "status": "succeeded", "latency_ms": 1200,
        "cost_usd": 0.0042, "error": "",
    }
    sql, parameters = script.calls[0]
    assert "r.pack = {pack:String}" in sql and "r.user_id = {user:String}" in sql and "r.status = {status:String}" in sql
    assert parameters == {"pack": "minimal", "user": "lab.analyst", "status": "succeeded", "start": date(2026, 11, 1),
                          "end": date(2026, 11, 6), "limit": PAGE_SIZE, "offset": PAGE_SIZE}


def test_a_trace_merges_nodes_llm_calls_sql_and_access_in_time_order(client):
    later = TS.replace(second=5)
    reader, _ = logs([
        (r"r\.trace_id = \{trace_id", [RUN]),
        (r"FROM agent_logs\.events", [(TS, "extract", "ok", 300)]),
        (r"FROM agent_logs\.llm_calls", [
            (TS.replace(second=1), "extract", "openai-small", "", "gpt-x", 120, 0.0004, 290, "ok", ""),
            (TS.replace(second=2), "summarize", "", "lab", "openai/house-model", 80, None, 150, "success", ""),
        ]),
        (r"FROM agent_logs\.sql_runs", [(later, 1, "SELECT 1", 1, "")]),
        (r"FROM agent_logs\.audit", [(TS.replace(second=3), "viewer", "ALLOW", "widget_sales", "")]),
    ])
    use(reader)

    body = client.get("/admin/runs/t1", headers=ADMIN).json()

    assert body["run"]["trace_id"] == "t1"
    assert [(item["kind"], item["name"], item["status"]) for item in body["items"]] == [
        ("node", "extract", "ok"), ("llm", "LLM extract", "ok"), ("llm", "LLM summarize", "ok"),
        ("access", "Access widget_sales", "ok"), ("sql", "SQL attempt 1", "ok"),
    ]
    assert body["items"][1]["meta"] == ["openai-small", "gpt-x", "120 tokens", "$0.000400"]
    # A gateway row names its provider; a model without a known price has no cost estimate.
    assert body["items"][2]["meta"] == ["lab", "openai/house-model", "80 tokens", "no price"]
    assert body["items"][4]["sql"] == "SELECT 1"


def test_an_unknown_trace_is_404(client):
    use(logs([])[0])
    assert client.get("/admin/runs/nope", headers=ADMIN).status_code == 404


def test_audit_denials_and_screening_verdicts(client):
    reader, script = logs([
        (r"FROM agent_logs\.audit", [(TS, "t1", "lab.marketing", "marketing", "DENY", "returns", ["returns"], "not granted")]),
        (r"FROM agent_logs\.input_screening", [(TS, "t2", "lab.analyst", "question", "block", "log", 0.97, ["en_override"])]),
    ])
    use(reader)

    audit = client.get("/admin/audit", headers=ADMIN, params={"decision": "DENY"}).json()
    screening = client.get("/admin/screening", headers=ADMIN, params={"verdict": "block", "source": "question"}).json()

    assert audit[0]["decision"] == "DENY" and audit[0]["blocked_tables"] == ["returns"]
    assert screening[0]["verdict"] == "block" and screening[0]["rule_hits"] == ["en_override"]
    assert script.calls[0][1]["decision"] == "DENY"
    assert script.calls[1][1] | {} == {"verdict": "block", "source": "question", "limit": PAGE_SIZE, "offset": 0}


def test_costs_are_grouped_with_their_provider(client):
    reader, script = logs([(r"FROM agent_logs\.llm_calls", [
        ("2026-11-05", "openai-small", "", "gpt-x", "fast", 12, 0.0123),
        ("2026-11-06", "", "lab", "openai/house-model", "sql-gen", 3, None),
    ])])
    use(reader)

    rows = client.get("/admin/costs", headers=ADMIN, params={"from": "2026-11-01", "to": "2026-11-06"}).json()

    # Rows of the proxy era take their provider from the alias; gateway rows store it.
    assert rows == [
        {"day": "2026-11-05", "alias": "openai-small", "model": "gpt-x", "tier": "fast", "provider": "openai", "calls": 12,
         "cost_usd": 0.0123},
        {"day": "2026-11-06", "alias": "", "model": "openai/house-model", "tier": "sql-gen", "provider": "lab", "calls": 3,
         "cost_usd": 0.0},
    ]
    assert script.calls[0][1] == {"start": date(2026, 11, 1), "end": date(2026, 11, 6)}


def test_an_admin_reads_a_conversation_its_owner_deleted(client):
    reader, _ = logs([
        (r"FROM agent_logs\.conversations FINAL WHERE conversation_id", [("c1", "lab.analyst", "Revenue", 1, TS)]),
        (r"FROM agent_logs\.conversations FINAL", [("c1", "lab.analyst", "Revenue", 1, TS)]),
        (r"FROM agent_logs\.chat_messages", [(TS, "user", "Revenue by widget", "t1", 1, 0)]),
    ])
    use(reader)

    listed = client.get("/admin/conversations", headers=ADMIN, params={"user": "lab.analyst"}).json()
    thread = client.get("/admin/conversations/c1", headers=ADMIN).json()

    assert listed[0]["deleted"] is True
    assert thread["conversation"]["deleted"] is True and thread["messages"][0]["content"] == "Revenue by widget"


@pytest.mark.parametrize("path", [
    "/admin/runs", "/admin/runs/t1", "/admin/audit", "/admin/screening", "/admin/costs", "/admin/conversations",
    "/admin/conversations/c1",
])
def test_only_an_admin_reads_the_run_logs(client, path):
    use(logs([])[0])
    assert client.get(path, headers=REVIEWER).status_code == 403


def test_an_unreachable_log_store_is_503(client):
    def broken(sql, parameters):
        raise RuntimeError("connection refused")

    use(AdminLogs(broken, "minimal"))
    assert client.get("/admin/runs", headers=ADMIN).status_code == 503
