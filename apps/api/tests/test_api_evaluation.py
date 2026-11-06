"""The Evaluation section: stored reports and one background eval run per pack."""

from datetime import UTC, date, datetime

from fastapi.testclient import TestClient
import pytest

from agent_fixtures import compiled_fixture
from auth_fixtures import token, verifier

from app.api import runtime
from app.eval.console import EvalReports, EvalRuns, RunInProgress
from app.eval.runner import EvalRun
from app.eval.scorers import CaseScore, LayerScore
from app.main import app

ADMIN = {"Authorization": f"Bearer {token(realm_access={'roles': ['admin']})}"}
REVIEWER = {"Authorization": f"Bearer {token(realm_access={'roles': ['pack_reviewer']})}"}
VIEWER = {"Authorization": f"Bearer {token()}"}
TS = datetime(2026, 11, 6, tzinfo=UTC)
PASS, FAIL, SKIP = LayerScore(status="pass"), LayerScore(status="fail", reason="no result"), LayerScore(status="not_scored")


def case(case_id, category, execution):
    return CaseScore(case_id=case_id, category=category, question="q", active=True,
                     layers={"intent": PASS, "extraction": PASS, "retrieval": SKIP, "execution": execution})


RUN = EvalRun(pack="minimal", reference_date=date(2026, 1, 15), threshold=0.8,
              cases=[case("a", "top_n", PASS), case("b", "top_n", PASS), case("c", "monthly_trend", FAIL)])


def reports(rows):
    return EvalReports(lambda sql, parameters: rows, "minimal")


@pytest.fixture
def client():
    app.dependency_overrides[runtime.get_verifier] = lambda: verifier()
    app.dependency_overrides[runtime.get_compiled_or_none] = lambda: compiled_fixture()
    app.dependency_overrides[runtime.get_eval_reports] = lambda: reports([("r1", TS, RUN.model_dump_json(), False)])
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_a_report_shows_layers_categories_and_failed_cases(client):
    body = client.get("/admin/eval-reports/r1", headers=REVIEWER).json()
    assert body["passed"] is False and body["threshold"] == 0.8 and body["regressed"] is False
    assert body["layers"]["execution"] == {"passed": 2, "failed": 1, "not_scored": 0}
    assert body["categories"] == {"monthly_trend": "0/1", "top_n": "2/2"}
    assert body["failed_cases"] == [{"case_id": "c", "category": "monthly_trend", "reason": "no result"}]
    assert [report["id"] for report in client.get("/admin/eval-reports", headers=ADMIN).json()] == ["r1"]


def test_an_unknown_report_is_404_and_a_viewer_is_refused(client):
    app.dependency_overrides[runtime.get_eval_reports] = lambda: reports([])
    assert client.get("/admin/eval-reports/nope", headers=ADMIN).status_code == 404
    assert client.get("/admin/eval-reports", headers=VIEWER).status_code == 403


def test_only_an_admin_starts_a_run_and_a_second_one_waits(client):
    started = []
    runs = EvalRuns(lambda pack: started.append(pack) or 0, start_thread=lambda target: None)
    app.dependency_overrides[runtime.get_eval_runs] = lambda: runs

    assert client.post("/admin/eval-runs", headers=REVIEWER).status_code == 403
    response = client.post("/admin/eval-runs", headers=ADMIN)
    assert response.status_code == 202 and response.json() == {"pack": "minimal", "running": True}
    assert client.post("/admin/eval-runs", headers=ADMIN).status_code == 409


def test_a_finished_run_frees_the_pack():
    executed = []
    runs = EvalRuns(lambda pack: executed.append(pack) or 0, start_thread=lambda target: target())
    runs.start("minimal")
    runs.start("minimal")
    assert executed == ["minimal", "minimal"] and not runs.running("minimal")


def test_a_running_pack_refuses_a_second_start():
    runs = EvalRuns(lambda pack: 0, start_thread=lambda target: None)
    runs.start("minimal")
    with pytest.raises(RunInProgress):
        runs.start("minimal")
