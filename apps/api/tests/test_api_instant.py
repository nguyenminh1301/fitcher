"""``/pack/instant``: start an instant pack from a connected source and follow its job (DECISIONS §11 step 0)."""

from fastapi.testclient import TestClient
import pytest
from session_fixtures import SessionHeaders

from app.api import instant as instant_api
from app.main import app
from app.onboarding.instant import InstantJob, InstantRefused

ADMIN = SessionHeaders(["admin"], user_id="lab.admin")
VIEWER = SessionHeaders()


class FakePipeline:
    def __init__(self):
        self.started: list[tuple] = []
        self.jobs: dict[str, InstantJob] = {}

    def estimate(self, source_id, tables):
        if "nope" in tables:
            raise InstantRefused("unknown table nope in source shop")
        return {"prompt_tokens": 1234, "datasets": 3, "model_missing": None}

    def start(self, source_id, tables, *, confirm_billable, started_by):
        if not confirm_billable:
            raise InstantRefused("drafting the pack is a billable model call: confirm it to start")
        self.started.append((source_id, tuple(tables), started_by))
        job = InstantJob(id="job1", source_id=source_id, tables=list(tables), started_by=started_by, started_at="2026-11-15T10:00:00+00:00")
        self.jobs[job.id] = job
        return job

    def job(self, job_id):
        return self.jobs.get(job_id)


class Actions:
    def __init__(self):
        self.records = []

    def record_action(self, record) -> None:
        self.records.append(record)


@pytest.fixture
def parts():
    pipeline, actions = FakePipeline(), Actions()
    app.dependency_overrides[instant_api.get_instant_pipeline] = lambda: pipeline
    app.dependency_overrides[instant_api.get_admin_action_log] = lambda: actions
    yield TestClient(app), pipeline, actions
    app.dependency_overrides.clear()


BODY = {"source_id": "shop", "tables": ["widgets", "sales"], "confirm_billable": True}


@pytest.mark.parametrize(("method", "path"), [
    ("post", "/pack/instant"), ("post", "/pack/instant/estimate"), ("get", "/pack/instant/job1")])
def test_every_endpoint_needs_the_admin_role(parts, method, path):
    client, _, _ = parts
    response = client.post(path, headers=VIEWER, json=BODY) if method == "post" else client.get(path, headers=VIEWER)

    assert response.status_code == 403


def test_the_estimate_shows_the_prompt_size_before_the_paid_call(parts):
    client, pipeline, _ = parts

    response = client.post("/pack/instant/estimate", headers=ADMIN, json={"source_id": "shop", "tables": ["widgets"]})

    assert response.status_code == 200
    assert response.json() == {"prompt_tokens": 1234, "datasets": 3, "model_missing": None}
    assert pipeline.started == []


def test_starting_without_the_confirmation_is_refused(parts):
    client, pipeline, _ = parts

    response = client.post("/pack/instant", headers=ADMIN, json={**BODY, "confirm_billable": False})

    assert response.status_code == 422 and "billable" in response.json()["detail"]
    assert pipeline.started == []


def test_a_confirmed_request_starts_one_job_and_records_the_admin_action(parts):
    client, pipeline, actions = parts

    response = client.post("/pack/instant", headers=ADMIN, json=BODY)

    assert response.status_code == 202
    assert response.json()["job"]["id"] == "job1" and response.json()["job"]["status"] == "running"
    assert pipeline.started == [("shop", ("widgets", "sales"), "lab.admin")]
    assert [(record.action, record.target) for record in actions.records] == [("pack.instant", "shop")]


def test_the_job_reports_its_steps_and_its_result(parts):
    client, pipeline, _ = parts
    client.post("/pack/instant", headers=ADMIN, json=BODY)
    job = pipeline.jobs["job1"]
    job.status, job.result = "succeeded", {"pack": "shop", "suggested_questions": ["Total sales?"]}

    body = client.get("/pack/instant/job1", headers=ADMIN).json()["job"]

    assert body["status"] == "succeeded" and body["result"]["suggested_questions"] == ["Total sales?"]
    assert [step["id"] for step in body["steps"]][0] == "marts"
    assert client.get("/pack/instant/other", headers=ADMIN).status_code == 404


def test_an_unknown_table_is_unprocessable(parts):
    client, _, _ = parts

    response = client.post("/pack/instant/estimate", headers=ADMIN, json={"source_id": "shop", "tables": ["nope"]})

    assert response.status_code == 422 and "nope" in response.json()["detail"]
