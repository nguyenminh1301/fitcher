"""The setup endpoints over a temporary app state."""

from fastapi.testclient import TestClient
import pytest

from auth_fixtures import token, verifier

from app.api import runtime, setup as setup_api
from app.main import app
from app.state import migrate
from app.state.db import StateDb

ADMIN = {"Authorization": f"Bearer {token(preferred_username='lab.admin', realm_access={'roles': ['admin']})}"}
VIEWER = {"Authorization": f"Bearer {token()}"}


@pytest.fixture
def client(tmp_path):
    db = StateDb(tmp_path / "app.db")
    migrate.apply_pending(db)
    app.dependency_overrides[runtime.get_verifier] = lambda: verifier()
    app.dependency_overrides[setup_api.get_state_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_status_of_a_new_instance(client):
    body = client.get("/setup/status", headers=ADMIN).json()
    assert body == {"mode": None, "steps": [{"id": "mode", "state": "pending"}, {"id": "models", "state": "pending"}],
                    "complete": False}


def test_any_signed_in_user_can_read_the_status_but_not_change_it(client):
    assert client.get("/setup/status", headers=VIEWER).status_code == 200
    assert client.put("/setup/mode", headers=VIEWER, json={"mode": "team"}).status_code == 403
    assert client.post("/setup/steps/mode/skip", headers=VIEWER).status_code == 403
    assert client.post("/setup/complete", headers=VIEWER).status_code == 403


def test_status_needs_a_token(client):
    assert client.get("/setup/status").status_code == 401


def test_choosing_a_mode_is_stored_and_shown_again(client):
    response = client.put("/setup/mode", headers=ADMIN, json={"mode": "team"})
    assert response.status_code == 200
    body = client.get("/setup/status", headers=ADMIN).json()
    assert body["mode"] == "team" and body["steps"][0] == {"id": "mode", "state": "done"}


def test_an_unknown_mode_is_refused(client):
    assert client.put("/setup/mode", headers=ADMIN, json={"mode": "everyone"}).status_code == 422


def test_skip_and_unknown_step(client):
    assert client.post("/setup/steps/mode/skip", headers=ADMIN).json()["steps"][0] == {"id": "mode", "state": "skipped"}
    assert client.post("/setup/steps/nope/skip", headers=ADMIN).status_code == 404


def test_complete_needs_every_step_answered(client):
    refused = client.post("/setup/complete", headers=ADMIN)
    assert refused.status_code == 409 and "mode" in refused.json()["detail"]
    client.put("/setup/mode", headers=ADMIN, json={"mode": "individual"})
    client.post("/setup/steps/models/skip", headers=ADMIN)
    done = client.post("/setup/complete", headers=ADMIN)
    assert done.status_code == 200 and done.json()["complete"] is True


def test_no_endpoint_returns_a_secret():
    paths = set(app.openapi()["paths"])
    assert not any("secret" in path for path in paths)
