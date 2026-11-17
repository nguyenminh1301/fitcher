"""The owner password over HTTP: status, sign-in and sign-out, setting and removing it, and the gate."""

from agent_fixtures import compiled_fixture
from fastapi.testclient import TestClient
import pytest

from app.api import runtime
from app.auth import owner
from app.main import app
from app.state.db import shared_state

PASSWORD = "correct horse battery"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("FITCHER_ALLOWED_HOSTS", raising=False)
    app.dependency_overrides[runtime.get_compiled_or_none] = compiled_fixture
    with TestClient(app, base_url="http://localhost:3000", client=("127.0.0.1", 50000)) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_without_a_password_every_request_from_this_computer_is_the_owner(client):
    assert client.get("/owner/status").json() == {"password_set": False, "signed_in": False, "exposed": False}
    assert client.get("/me").status_code == 200


def test_setting_the_password_signs_this_browser_in_and_locks_everyone_else_out(client):
    response = client.put("/owner/password", json={"new_password": PASSWORD})

    assert response.status_code == 204
    cookie = response.cookies.get(owner.SESSION_COOKIE)
    assert cookie and "httponly" in response.headers["set-cookie"].lower()
    assert "samesite=strict" in response.headers["set-cookie"].lower()
    assert client.get("/me").status_code == 200
    assert client.get("/owner/status").json()["signed_in"] is True

    client.cookies.clear()
    refused = client.get("/me")
    assert refused.status_code == 401 and refused.json() == {"detail": "sign in with the owner password"}
    assert client.get("/conversations").status_code == 401
    assert client.get("/owner/status").json() == {"password_set": True, "signed_in": False, "exposed": False}
    assert client.get("/health").status_code == 200


def test_signing_in_and_out(client):
    owner.set_password(shared_state(), PASSWORD)

    assert client.post("/owner/session", json={"password": "wrong password"}).status_code == 401
    assert client.post("/owner/session", json={"password": PASSWORD}).status_code == 204
    assert client.get("/me").status_code == 200

    assert client.delete("/owner/session").status_code == 204
    client.cookies.clear()
    assert client.get("/me").status_code == 401


def test_repeated_wrong_passwords_are_slowed_down(client):
    owner.set_password(shared_state(), PASSWORD)
    for _ in range(owner.FAILURE_LIMIT):
        client.post("/owner/session", json={"password": "wrong password"})

    refused = client.post("/owner/session", json={"password": PASSWORD})

    assert refused.status_code == 429 and int(refused.headers["retry-after"]) > 0


def test_signing_in_without_a_password_is_a_conflict(client):
    assert client.post("/owner/session", json={"password": PASSWORD}).status_code == 409


def test_changing_the_password_needs_the_current_one(client):
    client.put("/owner/password", json={"new_password": PASSWORD})

    assert client.put("/owner/password", json={"new_password": "another long one"}).status_code == 401
    assert client.put("/owner/password", json={"current_password": "wrong", "new_password": "another long one"}).status_code == 401
    assert client.put("/owner/password", json={"current_password": PASSWORD, "new_password": "short"}).status_code == 422
    assert client.put("/owner/password", json={"current_password": PASSWORD, "new_password": "another long one"}).status_code == 204
    assert owner.verify(shared_state(), "another long one")


def test_removing_the_password_opens_the_instance_to_this_computer_again(client):
    client.put("/owner/password", json={"new_password": PASSWORD})

    assert client.request("DELETE", "/owner/password", json={"current_password": "wrong"}).status_code == 401
    assert client.request("DELETE", "/owner/password", json={"current_password": PASSWORD}).status_code == 204
    client.cookies.clear()
    assert client.get("/me").status_code == 200


@pytest.mark.address_checks
def test_an_instance_reachable_from_other_machines_needs_a_password_first(client, monkeypatch):
    monkeypatch.setenv("FITCHER_ALLOWED_HOSTS", "fitcher.lan")
    remote = {"Host": "fitcher.lan", "X-Fitcher-Peer": "192.168.1.50", "Origin": "http://fitcher.lan"}

    refused = client.get("/me", headers=remote)
    assert refused.status_code == 403 and "owner password" in refused.json()["detail"]
    assert client.get("/owner/status", headers=remote).json() == {"password_set": False, "signed_in": False, "exposed": True}
    # The password can only be set from this computer.
    assert client.put("/owner/password", headers=remote, json={"new_password": PASSWORD}).status_code == 403
    local = {"Origin": "http://localhost:3000"}
    assert client.put("/owner/password", headers=local, json={"new_password": PASSWORD}).status_code == 204

    client.cookies.clear()
    assert client.get("/me", headers=remote).status_code == 401
    assert client.post("/owner/session", headers=remote, json={"password": PASSWORD}).status_code == 204
    assert client.get("/me", headers=remote).status_code == 200
    kept = client.request("DELETE", "/owner/password", headers=local, json={"current_password": PASSWORD})
    assert kept.status_code == 409 and "reachable" in kept.json()["detail"]
