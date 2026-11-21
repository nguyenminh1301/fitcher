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
RUN = ("t1", TS, "dev.analyst", "reader", "Revenue by widget", "data_query", "succeeded", 1200, 0.0042, "", 1500, 220,
       ["openai/nvidia/model:free", "gpt-x", ""], "minimal", False, "")


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
    app.dependency_overrides[runtime.get_compiled_or_none] = lambda: compiled_fixture()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def use(reader: AdminLogs):
    app.dependency_overrides[runtime.get_admin_logs] = lambda: reader


def test_a_run_says_when_its_cost_is_unknown_and_names_the_question_it_answered(client):
    answer = RUN[:4] + ("Năm nay",) + RUN[5:14] + (True, "Tổng amount theo region")
    reader, script = logs([(r"FROM agent_logs\.runs", [answer])])
    use(reader)

    run = client.get("/admin/runs", headers=ADMIN).json()[0]

    assert (run["question"], run["answer_to"], run["cost_unknown"]) == ("Năm nay", "Tổng amount theo region", True)
    sql = script.calls[0][0]
    assert "p.status = 'clarified'" in sql and "previous.next_turn = turns.turn" in sql


def test_runs_are_filtered_paged_and_scoped_to_the_pack(client):
    reader, script = logs([(r"FROM agent_logs\.runs", [RUN])])
    use(reader)

    response = client.get("/admin/runs", headers=ADMIN,
                          params={"user": "dev.analyst", "status": "succeeded", "from": "2026-11-01", "to": "2026-11-06", "page": 2})

    assert response.status_code == 200
    assert response.json()[0] == {
        "trace_id": "t1", "pack": "minimal", "ts": "2026-11-05T09:00:00Z", "user_id": "dev.analyst", "role": "reader",
        "question": "Revenue by widget", "intent": "data_query", "status": "succeeded", "latency_ms": 1200,
        "cost_usd": 0.0042, "error": "", "input_tokens": 1500, "output_tokens": 220, "models": ["nvidia/model:free", "gpt-x"], "cost_unknown": False, "answer_to": "",
    }
    sql, parameters = script.calls[0]
    assert "sum(prompt_tokens)" in sql and "status IN ('success', 'ok')" in sql
    assert "r.pack = {pack:String}" in sql and "r.user_id = {user:String}" in sql and "r.status = {status:String}" in sql
    assert parameters == {"pack": "minimal", "every_pack": False, "user": "dev.analyst", "status": "succeeded",
                          "start": date(2026, 11, 1), "end": date(2026, 11, 6), "limit": PAGE_SIZE, "offset": PAGE_SIZE}


def test_every_packs_runs_are_listed_on_request_each_with_its_pack(client):
    reader, script = logs([(r"FROM agent_logs\.runs", [RUN, (*RUN[:13], "other_source", *RUN[14:])])])
    use(reader)

    rows = client.get("/admin/runs", headers=ADMIN, params={"all": "true"}).json()

    assert [row["pack"] for row in rows] == ["minimal", "other_source"]
    assert script.calls[0][1]["every_pack"] is True


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
        (r"FROM agent_logs\.audit", [(TS.replace(second=3), "reader", "ALLOW", "widget_sales", "")]),
    ])
    use(reader)

    body = client.get("/admin/runs/t1", headers=ADMIN).json()

    assert body["run"]["trace_id"] == "t1"
    assert [(item["kind"], item["name"], item["status"]) for item in body["items"]] == [
        ("node", "extract", "ok"), ("llm", "LLM extract", "ok"), ("llm", "LLM summarize", "ok"),
        ("access", "Access widget_sales", "ok"), ("sql", "SQL attempt 1", "ok"),
    ]
    assert body["items"][1]["meta"] == ["openai-small", "gpt-x", "120 tokens", "$0.000400"]
    # A gateway row names its provider without the SDK prefix; a model without a known price says so.
    assert body["items"][2]["meta"] == ["lab", "house-model", "80 tokens", "price unknown"]
    assert body["items"][4]["sql"] == "SELECT 1"


def test_an_unknown_trace_is_404(client):
    use(logs([])[0])
    assert client.get("/admin/runs/nope", headers=ADMIN).status_code == 404


def test_audit_denials_and_screening_verdicts(client):
    reader, script = logs([
        (r"FROM agent_logs\.audit", [(TS, "t1", "dev.marketing", "marketing", "DENY", "returns", ["returns"], "not granted")]),
        (r"FROM agent_logs\.input_screening", [(TS, "t2", "dev.analyst", "question", "block", "log", 0.97, ["en_override"])]),
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
        ("2026-11-05", "openai-small", "", "gpt-x", "fast", 12, 0.0123, 4800, 610),
        ("2026-11-06", "", "lab", "openai/house-model", "sql-gen", 3, None, None, None),
    ])])
    use(reader)

    rows = client.get("/admin/costs", headers=ADMIN, params={"from": "2026-11-01", "to": "2026-11-06"}).json()

    # Rows of the proxy era take their provider from the alias; gateway rows store it.
    assert rows == [
        {"day": "2026-11-05", "alias": "openai-small", "model": "gpt-x", "tier": "fast", "provider": "openai", "calls": 12,
         "cost_usd": 0.0123, "input_tokens": 4800, "output_tokens": 610},
        {"day": "2026-11-06", "alias": "", "model": "openai/house-model", "tier": "sql-gen", "provider": "lab", "calls": 3,
         "cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0},
    ]
    assert script.calls[0][1] == {"start": date(2026, 11, 1), "end": date(2026, 11, 6)}


def test_an_unreachable_log_store_is_503(client):
    def broken(sql, parameters):
        raise RuntimeError("connection refused")

    use(AdminLogs(broken, "minimal"))
    assert client.get("/admin/runs", headers=ADMIN).status_code == 503


def test_median_latency_is_read_per_provider_and_model_without_the_sdk_prefix():
    reader, script = logs([(r"quantileExact", [("groq", "openai/openai/gpt-oss-120b", 840.0), ("gemini", "gemini/gemini-2.5-flash", 1200)])])

    assert reader.median_latency() == {("groq", "openai/gpt-oss-120b"): 840, ("gemini", "gemini-2.5-flash"): 1200}
    sql, parameters = script.calls[0]
    assert "status IN ('success', 'ok')" in sql and parameters == {"days": 7}


def test_costs_can_be_limited_to_one_packs_questions(client):
    reader, script = logs([(r"FROM agent_logs\.llm_calls", [])])
    use(reader)

    client.get("/admin/costs", headers=ADMIN, params={"from": "2026-11-01", "to": "2026-11-06", "pack": "music"})

    sql, parameters = script.calls[0]
    assert "SELECT trace_id FROM agent_logs.runs WHERE pack = {pack:String}" in sql and parameters["pack"] == "music"


def test_a_pack_parameter_must_be_a_pack_name(client):
    use(logs([])[0])

    assert client.get("/admin/runs", headers=ADMIN, params={"pack": "../etc"}).status_code == 422
