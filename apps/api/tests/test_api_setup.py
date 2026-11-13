"""The setup endpoints, and changing between individual and team mode."""

from fastapi.testclient import TestClient
import pytest

from agent_fixtures import compiled_fixture
from session_fixtures import sign_in

from app.api import runtime
from app.auth import accounts
from app.main import app
from app.state.db import shared_state
from app.state.settings import Settings

PACK_ROLES = [role.id for role in compiled_fixture().pack.policies.roles]
FIRST_ADMIN = {"email": "Ana@Example.com", "display_name": "Ana", "password": "correct horse"}
SAME_ORIGIN = {"Origin": "http://localhost"}


@pytest.fixture
def client():
    app.dependency_overrides[runtime.get_compiled_or_none] = compiled_fixture
    with TestClient(app, base_url="http://localhost") as test_client:
        yield test_client
    app.dependency_overrides.clear()


def individual() -> None:
    Settings(shared_state()).set("instance", "mode", "individual")


def test_status_of_a_new_instance(client):
    with shared_state().write() as conn:
        conn.execute("DELETE FROM settings")

    body = client.get("/setup/status").json()

    assert body == {"mode": None, "steps": [{"id": "mode", "state": "pending"}, {"id": "models", "state": "pending"}],
                    "complete": False}


def test_any_signed_in_user_can_read_the_status_but_not_change_it(client):
    sign_in(client, "lab.viewer", ["viewer"])

    assert client.get("/setup/status").status_code == 200
    assert client.put("/setup/mode", json={"mode": "team"}).status_code == 403
    assert client.post("/setup/steps/mode/skip").status_code == 403
    assert client.post("/setup/complete").status_code == 403


def test_status_needs_a_signed_in_user_in_team_mode(client):
    assert client.get("/setup/status").status_code == 401


def test_an_unknown_mode_is_refused(client):
    sign_in(client, "root", ["admin"])

    assert client.put("/setup/mode", json={"mode": "everyone"}).status_code == 422


def test_skip_and_unknown_step(client):
    sign_in(client, "root", ["admin"])

    assert client.post("/setup/steps/mode/skip").json()["steps"][0] == {"id": "mode", "state": "skipped"}
    assert client.post("/setup/steps/nope/skip").status_code == 404


def test_complete_needs_every_step_answered(client):
    individual()
    refused = client.post("/setup/complete", headers=SAME_ORIGIN)
    assert refused.status_code == 409 and "mode" in refused.json()["detail"]

    client.put("/setup/mode", headers=SAME_ORIGIN, json={"mode": "individual"})
    client.post("/setup/steps/models/skip", headers=SAME_ORIGIN)
    done = client.post("/setup/complete", headers=SAME_ORIGIN)

    assert done.status_code == 200 and done.json()["complete"] is True


def test_moving_to_team_mode_needs_the_first_admin(client):
    individual()

    response = client.put("/setup/mode", headers=SAME_ORIGIN, json={"mode": "team"})

    assert response.status_code == 422
    assert Settings(shared_state()).get("instance", "mode") == "individual"


def test_moving_to_team_mode_makes_the_owner_the_first_admin_and_signs_them_in(client):
    individual()

    response = client.put("/setup/mode", headers=SAME_ORIGIN, json={"mode": "team", "admin": FIRST_ADMIN})

    assert response.status_code == 200
    assert response.json()["mode"] == "team"
    admin = accounts.get(shared_state(), "owner")
    assert (admin.email, admin.roles) == ("ana@example.com", tuple(sorted([*PACK_ROLES, "admin"])))
    me = client.get("/me").json()
    assert (me["user_id"], me["mode"]) == ("owner", "team")


def test_a_weak_first_admin_password_is_refused(client):
    individual()

    response = client.put("/setup/mode", headers=SAME_ORIGIN,
                          json={"mode": "team", "admin": {**FIRST_ADMIN, "password": "short"}})

    assert response.status_code == 422
    assert accounts.list_all(shared_state()) == []


def test_moving_back_to_individual_is_refused_while_two_accounts_are_enabled(client):
    sign_in(client, "root", ["admin"])
    other = accounts.create(shared_state(), "bea@example.com", "Bea", "correct horse", ["viewer"])

    refused = client.put("/setup/mode", json={"mode": "individual"})
    assert refused.status_code == 409
    assert "one enabled account" in refused.json()["detail"]

    accounts.update(shared_state(), other.id, enabled=False)
    assert client.put("/setup/mode", json={"mode": "individual"}).json()["mode"] == "individual"


def test_no_endpoint_returns_a_secret():
    paths = set(app.openapi()["paths"])
    assert not any("secret" in path for path in paths)
