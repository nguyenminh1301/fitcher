"""OIDC settings for an admin, and signing in through the provider's endpoints."""

from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient
import pytest

from agent_fixtures import compiled_fixture
from oidc_fixtures import CLIENT_ID, CLIENT_SECRET, ISSUER, FakeProvider
from session_fixtures import sign_in

from app.api import runtime
from app.auth import accounts
from app.main import app
from app.state.db import shared_state
from app.state.settings import Settings

CONFIG = {"issuer": ISSUER, "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "roles_claim": "groups"}


class ActionLog:
    def __init__(self):
        self.records = []

    def record_action(self, record):
        self.records.append(record)


@pytest.fixture
def idp():
    return FakeProvider()


@pytest.fixture
def log():
    return ActionLog()


@pytest.fixture
def client(idp, log):
    app.dependency_overrides[runtime.get_compiled_or_none] = compiled_fixture
    app.dependency_overrides[runtime.get_oidc_http] = idp.client
    app.dependency_overrides[runtime.get_admin_action_log] = lambda: log
    with TestClient(app, base_url="http://localhost:3000", follow_redirects=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def configured(client, log):
    sign_in(client, "root", ["admin"])
    assert client.put("/settings/oidc", json=CONFIG).status_code == 200
    client.cookies.clear()
    log.records.clear()
    return client


def test_an_admin_registers_the_provider_and_its_secret_is_never_returned(client, log):
    sign_in(client, "root", ["admin"])

    response = client.put("/settings/oidc", json=CONFIG)

    assert response.status_code == 200
    assert response.json() == {
        "configured": True, "issuer": ISSUER, "client_id": CLIENT_ID, "roles_claim": "groups",
        "secret_set": True, "secret_last_four": "1234", "redirect_uri": "http://localhost:3000/auth/oidc/callback",
    }
    assert CLIENT_SECRET not in client.get("/settings/oidc").text
    assert [(r.action, r.target) for r in log.records] == [("oidc_settings", ISSUER)]
    assert CLIENT_SECRET not in log.records[0].new_value


def test_a_change_without_a_secret_keeps_the_stored_one(client):
    sign_in(client, "root", ["admin"])
    client.put("/settings/oidc", json=CONFIG)

    response = client.put("/settings/oidc", json={**CONFIG, "client_secret": None, "roles_claim": "roles"})

    assert response.json()["roles_claim"] == "roles"
    assert response.json()["secret_last_four"] == "1234"


def test_the_first_registration_needs_a_secret(client):
    sign_in(client, "root", ["admin"])

    assert client.put("/settings/oidc", json={**CONFIG, "client_secret": None}).status_code == 422


def test_a_provider_whose_discovery_fails_is_not_saved(client):
    sign_in(client, "root", ["admin"])

    response = client.put("/settings/oidc", json={**CONFIG, "issuer": "https://idp.example.com/realms/missing"})

    assert response.status_code == 422
    assert client.get("/settings/oidc").json()["configured"] is False


def test_removing_the_provider_turns_oidc_sign_in_off(configured, log):
    sign_in(configured, "root", ["admin"])

    assert configured.delete("/settings/oidc").status_code == 204

    assert configured.get("/settings/oidc").json()["configured"] is False
    assert configured.get("/session/oidc").json() == {"enabled": False}
    assert [r.action for r in log.records] == ["oidc_settings_removed"]


def test_only_an_admin_reads_or_changes_the_provider(client):
    sign_in(client, "lab.viewer", ["viewer"])

    assert client.get("/settings/oidc").status_code == 403
    assert client.put("/settings/oidc", json=CONFIG).status_code == 403
    assert client.delete("/settings/oidc").status_code == 403


def test_the_sign_in_page_learns_whether_oidc_is_on(client, configured):
    assert client.get("/session/oidc").json() == {"enabled": True}


def test_signing_in_through_the_provider_creates_the_account_and_its_session(configured, idp):
    start = configured.get("/session/oidc/start")
    assert start.status_code == 302
    query = {key: values[0] for key, values in parse_qs(urlsplit(start.headers["location"]).query).items()}
    assert start.headers["location"].startswith(f"{ISSUER}/protocol/openid-connect/auth?")
    code = idp.issue_code(query["nonce"], query["code_challenge"], query["redirect_uri"])

    done = configured.get("/session/oidc/callback", params={"state": query["state"], "code": code})

    # A page of this site moves on to "/": a redirect would still belong to the provider's cross-site
    # navigation, and the browser would not send the SameSite=Strict cookie with it.
    assert done.status_code == 200
    assert '<meta http-equiv="refresh" content="0;url=/">' in done.text
    assert "fitcher_session=" in done.headers["set-cookie"]
    assert done.headers["cache-control"] == "no-store"
    me = configured.get("/me").json()
    assert (me["display_name"], me["roles"]) == ("Carol", ["viewer"])


def test_a_failed_callback_returns_to_the_sign_in_page_without_a_session(configured):
    done = configured.get("/session/oidc/callback", params={"state": "unknown", "code": "x"})

    assert done.status_code == 303
    assert done.headers["location"] == "/sign-in?error=oidc"
    assert "set-cookie" not in done.headers


def test_a_provider_error_returns_to_the_sign_in_page(configured):
    done = configured.get("/session/oidc/callback", params={"error": "access_denied", "state": "s"})

    assert done.headers["location"] == "/sign-in?error=oidc"


def test_oidc_is_off_until_a_provider_is_registered(client):
    assert client.get("/session/oidc").json() == {"enabled": False}
    assert client.get("/session/oidc/start").status_code == 404


def test_oidc_is_off_in_individual_mode(configured):
    Settings(shared_state()).set("instance", "mode", "individual")

    assert configured.get("/session/oidc").json() == {"enabled": False}
    assert configured.get("/session/oidc/start").status_code == 404
    assert accounts.list_all(shared_state())[0].id == "root"
