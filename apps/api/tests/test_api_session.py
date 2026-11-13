"""Signing in and out with a local account, and the session cookie on later requests."""

from agent_fixtures import compiled_fixture
from fastapi.testclient import TestClient
import pytest

from app.api import runtime
from app.auth import accounts
from app.main import app
from app.state.db import shared_state

PASSWORD = "correct horse"
SIGN_IN = {"email": "Ana@Example.com", "password": PASSWORD}


@pytest.fixture
def account():
    return accounts.create(shared_state(), "ana@example.com", "Ana", PASSWORD, ["viewer"])


def make_client(base_url: str = "http://testserver"):
    app.dependency_overrides[runtime.get_compiled] = compiled_fixture
    app.dependency_overrides[runtime.get_compiled_or_none] = compiled_fixture
    return TestClient(app, base_url=base_url)


@pytest.fixture
def client():
    with make_client() as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_signing_in_sets_a_strict_http_only_session_cookie(client, account):
    response = client.post("/session", json=SIGN_IN)

    assert response.status_code == 204
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("fitcher_session=")
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    assert "Path=/" in cookie
    assert "Secure" not in cookie


def test_the_cookie_is_secure_when_the_request_came_over_https(account):
    with make_client("https://testserver") as client:
        response = client.post("/session", json=SIGN_IN)
    app.dependency_overrides.clear()

    assert "Secure" in response.headers["set-cookie"]


def test_the_session_cookie_identifies_the_account_on_later_requests(client, account):
    client.post("/session", json=SIGN_IN)

    response = client.get("/me")

    assert response.status_code == 200
    assert response.json() == {"user_id": account.id, "display_name": "Ana", "roles": ["viewer"], "active_role": "viewer"}


@pytest.mark.parametrize("body", [
    {"email": "ana@example.com", "password": "wrong horse"},
    {"email": "nobody@example.com", "password": PASSWORD},
])
def test_a_failed_sign_in_never_says_whether_the_account_exists(client, account, body):
    response = client.post("/session", json=body)

    assert response.status_code == 401
    assert response.json() == {"detail": "invalid email or password"}
    assert "set-cookie" not in response.headers


def test_repeated_failures_slow_down_even_the_right_password(client, account):
    for _ in range(5):
        assert client.post("/session", json={**SIGN_IN, "password": "wrong horse"}).status_code == 401

    response = client.post("/session", json=SIGN_IN)

    assert response.status_code == 429
    assert int(response.headers["retry-after"]) > 0


def test_signing_out_ends_the_session_and_clears_the_cookie(client, account):
    client.post("/session", json=SIGN_IN)
    token = client.cookies["fitcher_session"]

    response = client.delete("/session")

    assert response.status_code == 204
    assert 'fitcher_session=""' in response.headers["set-cookie"]
    client.cookies.set("fitcher_session", token)
    assert client.get("/me").status_code == 401


def test_an_unknown_session_cookie_is_unauthorized(client):
    client.cookies.set("fitcher_session", "not-a-session")

    assert client.get("/me").status_code == 401


def test_a_disabled_account_is_signed_out_on_its_next_request(client, account):
    accounts.create(shared_state(), "admin@example.com", "Admin", PASSWORD, ["admin"])
    client.post("/session", json=SIGN_IN)

    accounts.update(shared_state(), account.id, enabled=False)

    assert client.get("/me").status_code == 401
