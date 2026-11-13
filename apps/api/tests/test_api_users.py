"""The Users section on local accounts (DECISIONS §9, §15)."""

from fastapi.testclient import TestClient
import pytest

from agent_fixtures import compiled_fixture
from session_fixtures import PASSWORD, sign_in

from app.api import runtime
from app.auth import accounts, sessions
from app.main import app
from app.state.db import shared_state

NEW = {"email": "Bea@Example.com", "display_name": "Bea", "password": "battery staple", "roles": ["viewer"]}


class ActionLog:
    def __init__(self):
        self.records = []

    def record_action(self, record):
        self.records.append(record)

    def summary(self):
        return [(r.actor, r.action, r.target, r.old_value, r.new_value) for r in self.records]


@pytest.fixture
def setup():
    log = ActionLog()
    app.dependency_overrides[runtime.get_compiled_or_none] = compiled_fixture
    app.dependency_overrides[runtime.get_admin_action_log] = lambda: log
    with TestClient(app) as client:
        sign_in(client, "root", ["admin"])
        yield client, log
    app.dependency_overrides.clear()


def create(client, **overrides):
    response = client.post("/admin/users", json={**NEW, **overrides})
    assert response.status_code == 201, response.text
    return response.json()


def test_an_admin_creates_an_account_that_can_sign_in(setup):
    client, log = setup

    user = create(client)

    assert user == {"id": user["id"], "email": "bea@example.com", "display_name": "Bea", "roles": ["viewer"],
                    "enabled": True}
    assert accounts.authenticate(shared_state(), "bea@example.com", "battery staple").id == user["id"]
    assert log.summary() == [("root", "user_created", user["id"], "null", '{"email": "bea@example.com", "roles": ["viewer"]}')]


def test_the_list_shows_every_account_with_its_pack_and_console_roles(setup):
    client, _ = setup
    create(client, roles=["pack_reviewer", "viewer"])

    users = client.get("/admin/users").json()

    assert [(user["email"], user["roles"]) for user in users] == [
        ("bea@example.com", ["viewer", "pack_reviewer"]), ("root@example.com", ["admin"]),
    ]


@pytest.mark.parametrize(("body", "code"), [
    ({"roles": ["no_such_role"]}, 422),
    ({"password": "short"}, 422),
    ({"email": "not-an-email"}, 422),
    ({"email": "ROOT@example.com"}, 409),
])
def test_create_refusals(setup, body, code):
    client, log = setup

    assert client.post("/admin/users", json={**NEW, **body}).status_code == code
    assert log.records == []


def test_patch_changes_roles_name_and_status_and_records_each_change(setup):
    client, log = setup
    user = create(client)
    log.records.clear()

    response = client.patch(f"/admin/users/{user['id']}", json={"display_name": "Bea B", "roles": ["pack_reviewer"], "enabled": False})

    assert response.status_code == 200
    assert response.json() == {**user, "display_name": "Bea B", "roles": ["pack_reviewer"], "enabled": False}
    assert log.summary() == [
        ("root", "user_display_name", user["id"], '"Bea"', '"Bea B"'),
        ("root", "user_roles", user["id"], '["viewer"]', '["pack_reviewer"]'),
        ("root", "user_enabled", user["id"], "true", "false"),
    ]


def test_disabling_signs_the_user_out_at_once(setup):
    client, _ = setup
    user = create(client)
    token = sessions.start(shared_state(), user["id"])

    client.patch(f"/admin/users/{user['id']}", json={"enabled": False})

    assert sessions.principal_for(shared_state(), token) is None


@pytest.mark.parametrize("body", [{"enabled": False}, {"roles": ["viewer"]}])
def test_the_last_admin_cannot_be_disabled_or_demoted(setup, body):
    client, log = setup

    response = client.patch("/admin/users/root", json=body)

    assert response.status_code == 409
    assert log.records == []
    assert accounts.get(shared_state(), "root").roles == ("admin",)


@pytest.mark.parametrize(("method", "path", "body"), [
    ("PATCH", "/admin/users/nope", {"enabled": False}),
    ("POST", "/admin/users/nope/password", {"password": "battery staple"}),
])
def test_an_unknown_user_is_not_found(setup, method, path, body):
    client, _ = setup

    assert client.request(method, path, json=body).status_code == 404


def test_patch_refuses_a_role_the_instance_does_not_have(setup):
    client, _ = setup
    user = create(client)

    assert client.patch(f"/admin/users/{user['id']}", json={"roles": ["no_such_role"]}).status_code == 422


def test_a_password_reset_replaces_the_password_and_ends_the_sessions(setup):
    client, log = setup
    user = create(client)
    token = sessions.start(shared_state(), user["id"])
    log.records.clear()

    response = client.post(f"/admin/users/{user['id']}/password", json={"password": "new password"})

    assert response.status_code == 204
    assert sessions.principal_for(shared_state(), token) is None
    assert accounts.authenticate(shared_state(), "bea@example.com", "new password") is not None
    assert log.summary() == [("root", "user_password", user["id"], "null", "null")]


def test_a_reset_to_a_short_password_is_refused(setup):
    client, _ = setup
    user = create(client)

    assert client.post(f"/admin/users/{user['id']}/password", json={"password": "short"}).status_code == 422


def test_only_an_admin_manages_users(setup):
    client, _ = setup
    sign_in(client, "lab.viewer", ["viewer"])

    assert client.get("/admin/users").status_code == 403
    assert client.post("/admin/users", json=NEW).status_code == 403
    assert client.patch("/admin/users/root", json={"enabled": False}).status_code == 403


def test_the_password_is_never_returned(setup):
    client, _ = setup
    create(client)

    assert PASSWORD not in client.get("/admin/users").text
    assert "battery staple" not in client.get("/admin/users").text
