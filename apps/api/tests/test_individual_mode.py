"""Individual mode: one owner without sign-in, reachable only through allowed hosts and same-origin changes."""

from fastapi.testclient import TestClient
import pytest

from agent_fixtures import compiled_fixture

from app.api import runtime
from app.main import app
from app.state.db import shared_state
from app.state.settings import Settings

PACK_ROLES = [role.id for role in compiled_fixture().pack.policies.roles]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("FITCHER_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("FITCHER_INTERNAL_HOSTS", raising=False)
    Settings(shared_state()).set("instance", "mode", "individual")
    app.dependency_overrides[runtime.get_compiled] = compiled_fixture
    app.dependency_overrides[runtime.get_compiled_or_none] = compiled_fixture
    with TestClient(app, base_url="http://localhost:3000") as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_every_request_acts_as_the_owner_with_every_role(client):
    response = client.get("/me")

    assert response.status_code == 200
    assert response.json() == {
        "user_id": "owner", "display_name": "Owner", "roles": [*PACK_ROLES, "pack_reviewer", "admin"],
        "active_role": PACK_ROLES[0], "mode": "individual", "exposed": False,
    }


def test_the_owner_reaches_admin_sections_without_signing_in(client):
    assert client.get("/admin/users").status_code == 200


def test_a_new_instance_without_a_chosen_mode_is_individual(client):
    with shared_state().write() as conn:
        conn.execute("DELETE FROM settings WHERE group_name = 'instance'")

    assert client.get("/me").json()["mode"] == "individual"


@pytest.mark.parametrize("host", ["localhost", "localhost:3000", "127.0.0.1:8000", "[::1]:3000"])
def test_loopback_hosts_are_accepted(client, host):
    assert client.get("/me", headers={"Host": host}).status_code == 200


@pytest.mark.parametrize("host", ["example.com", "evil.localhost.example", "10.0.0.5:3000", ""])
def test_a_foreign_host_is_refused(client, host):
    response = client.get("/me", headers={"Host": host})

    assert response.status_code == 403
    assert "FITCHER_ALLOWED_HOSTS" in response.json()["detail"]


def test_an_allowed_host_is_accepted_and_reported_as_exposed(client, monkeypatch):
    monkeypatch.setenv("FITCHER_ALLOWED_HOSTS", "fitcher.lan, 192.168.1.20")

    response = client.get("/me", headers={"Host": "fitcher.lan:3000"})

    assert response.status_code == 200
    assert response.json()["exposed"] is True
    assert client.get("/me", headers={"Host": "192.168.1.20"}).status_code == 200


def test_an_internal_host_is_accepted_without_exposing_the_instance(client, monkeypatch):
    monkeypatch.setenv("FITCHER_INTERNAL_HOSTS", "api")

    response = client.get("/me", headers={"Host": "api:8000"})

    assert response.status_code == 200
    assert response.json()["exposed"] is False


def test_a_forwarded_host_must_be_allowed_too(client, monkeypatch):
    monkeypatch.setenv("FITCHER_INTERNAL_HOSTS", "api")

    assert client.get("/me", headers={"Host": "api:8000", "X-Forwarded-Host": "localhost:3000"}).status_code == 200
    assert client.get("/me", headers={"Host": "api:8000", "X-Forwarded-Host": "example.com"}).status_code == 403


@pytest.mark.parametrize("headers", [
    {},
    {"Origin": "http://example.com"},
    {"Origin": "http://localhost:3001"},
    {"Origin": "null"},
])
def test_a_change_without_the_same_origin_is_refused(client, headers):
    response = client.post("/setup/steps/models/skip", headers=headers)

    assert response.status_code == 403


def test_a_change_from_the_same_origin_is_accepted(client):
    assert client.post("/setup/steps/models/skip", headers={"Origin": "http://localhost:3000"}).status_code == 200


def test_a_change_forwarded_by_the_web_server_compares_the_browser_origin(client, monkeypatch):
    monkeypatch.setenv("FITCHER_INTERNAL_HOSTS", "api")
    forwarded = {"Host": "api:8000", "X-Forwarded-Host": "localhost:3000"}

    assert client.post("/setup/steps/models/skip", headers={**forwarded, "Origin": "http://localhost:3000"}).status_code == 200
    assert client.post("/setup/steps/models/skip", headers={**forwarded, "Origin": "http://api:8000"}).status_code == 403


def test_team_mode_checks_no_host(client):
    Settings(shared_state()).set("instance", "mode", "team")

    assert client.get("/pack", headers={"Host": "example.com"}).status_code == 200
    assert client.get("/me", headers={"Host": "example.com"}).status_code == 401
