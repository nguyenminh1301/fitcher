"""The setup endpoints: each step's state, skipping a step, and completing the setup."""

from fastapi.testclient import TestClient
import pytest

from agent_fixtures import compiled_fixture

from app.api import runtime
from app.main import app
from app.state.db import shared_state


@pytest.fixture
def client():
    app.dependency_overrides[runtime.get_compiled_or_none] = compiled_fixture
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_status_of_a_new_instance(client):
    with shared_state().write() as conn:
        conn.execute("DELETE FROM settings")
        conn.execute("DELETE FROM setup_steps")

    body = client.get("/setup/status").json()

    assert body == {"steps": [{"id": "models", "state": "pending"}, {"id": "data", "state": "pending"},
                              {"id": "documents", "state": "pending"}], "complete": False}


def test_skip_and_unknown_step(client):
    assert client.post("/setup/steps/models/skip").json()["steps"][0] == {"id": "models", "state": "skipped"}
    assert client.post("/setup/steps/nope/skip").status_code == 404
    # Who uses the instance is no longer a step: fitcher is a personal app.
    assert client.post("/setup/steps/mode/skip").status_code == 404
    assert client.put("/setup/mode", json={"mode": "team"}).status_code in (404, 405)


def test_complete_needs_every_step_answered(client):
    with shared_state().write() as conn:
        conn.execute("DELETE FROM setup_steps")
    refused = client.post("/setup/complete")
    assert refused.status_code == 409 and "models" in refused.json()["detail"]

    for step in ("models", "data", "documents"):
        client.post(f"/setup/steps/{step}/skip")
    done = client.post("/setup/complete")

    assert done.status_code == 200 and done.json()["complete"] is True


def test_no_endpoint_returns_a_secret():
    paths = set(app.openapi()["paths"])
    assert not any("secret" in path for path in paths)
