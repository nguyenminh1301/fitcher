"""The Users section over a fake Keycloak Admin REST API (httpx MockTransport)."""

import json

from fastapi.testclient import TestClient
import httpx
import pytest

from agent_fixtures import compiled_fixture
from auth_fixtures import token, verifier

from app.api import runtime
from app.auth.keycloak_admin import KeycloakAdmin
from app.main import app

ADMIN = {"Authorization": f"Bearer {token(preferred_username='lab.admin', realm_access={'roles': ['admin']})}"}
VIEWER = {"Authorization": f"Bearer {token()}"}


class FakeKeycloak:
    def __init__(self):
        self.users = {
            "u1": {"id": "u1", "username": "lab.analyst", "firstName": "Lab", "lastName": "Analyst", "enabled": True},
            "u2": {"id": "u2", "username": "lab.admin", "firstName": "Lab", "lastName": "Admin", "enabled": True},
            "s1": {"id": "s1", "username": "service-account-fitcher-admin-api", "enabled": True},
        }
        self.roles = {"u1": {"viewer", "pack_reviewer"}, "u2": {"admin"}, "s1": set()}
        self.realm_roles = {"viewer", "pack_reviewer", "admin"}
        self.tokens = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        if path.endswith("/protocol/openid-connect/token"):
            self.tokens += 1
            return httpx.Response(200, json={"access_token": "t", "expires_in": 300})
        assert request.headers["Authorization"] == "Bearer t"
        parts = path.split("/admin/realms/finch")[1].strip("/").split("/")
        if parts == ["users"]:
            return httpx.Response(200, json=list(self.users.values()))
        user_id = parts[1]
        if user_id not in self.users:
            return httpx.Response(404, json={})
        if len(parts) == 2:
            if method == "PUT":
                self.users[user_id].update(json.loads(request.content))
                return httpx.Response(204)
            return httpx.Response(200, json=self.users[user_id])
        if parts[2:] == ["role-mappings", "realm"]:
            if method == "GET":
                return httpx.Response(200, json=[{"id": r, "name": r} for r in sorted(self.roles[user_id])])
            names = {role["name"] for role in json.loads(request.content)}
            self.roles[user_id] = self.roles[user_id] | names if method == "POST" else self.roles[user_id] - names
            return httpx.Response(204)
        if parts[2:] == ["role-mappings", "realm", "available"]:
            return httpx.Response(200, json=[{"id": r, "name": r} for r in sorted(self.realm_roles - self.roles[user_id])])
        raise AssertionError(f"unexpected {method} {path}")


class ActionLog:
    def __init__(self):
        self.records = []

    def record_action(self, record):
        self.records.append(record)


@pytest.fixture
def setup():
    fake, log = FakeKeycloak(), ActionLog()
    admin = KeycloakAdmin("http://keycloak:8080", "finch", "fitcher-admin-api", "secret",
                          http=httpx.Client(transport=httpx.MockTransport(fake)))
    app.dependency_overrides[runtime.get_verifier] = lambda: verifier()
    app.dependency_overrides[runtime.get_compiled_or_none] = lambda: compiled_fixture()
    app.dependency_overrides[runtime.get_keycloak_admin] = lambda: admin
    app.dependency_overrides[runtime.get_admin_action_log] = lambda: log
    with TestClient(app) as client:
        yield client, fake, log
    app.dependency_overrides.clear()


def test_users_list_their_pack_roles_and_hide_service_accounts(setup):
    client, fake, _ = setup
    users = client.get("/admin/users", headers=ADMIN).json()
    assert users == [
        {"id": "u1", "username": "lab.analyst", "display_name": "Lab Analyst", "roles": ["viewer"], "enabled": True},
        {"id": "u2", "username": "lab.admin", "display_name": "Lab Admin", "roles": [], "enabled": True},
    ]
    assert fake.tokens == 1


def test_setting_roles_changes_only_pack_roles_and_is_recorded(setup):
    client, fake, log = setup
    assert client.put("/admin/users/u1/roles", headers=ADMIN, json={"roles": []}).json()["roles"] == []
    assert fake.roles["u1"] == {"pack_reviewer"}
    assert client.put("/admin/users/u1/roles", headers=ADMIN, json={"roles": ["viewer"]}).json()["roles"] == ["viewer"]
    assert fake.roles["u1"] == {"viewer", "pack_reviewer"}
    assert [(r.actor, r.action, r.target, r.old_value, r.new_value) for r in log.records] == [
        ("lab.admin", "user_roles", "u1", '["viewer"]', "[]"), ("lab.admin", "user_roles", "u1", "[]", '["viewer"]'),
    ]


@pytest.mark.parametrize(("method", "path", "body", "code"), [
    ("PUT", "/admin/users/u1/roles", {"roles": ["admin"]}, 422),
    ("PUT", "/admin/users/u2/roles", {"roles": ["viewer"]}, 409),
    ("POST", "/admin/users/u2/disable", None, 409),
    ("PUT", "/admin/users/nope/roles", {"roles": []}, 404),
])
def test_refusals(setup, method, path, body, code):
    client, _, log = setup
    assert client.request(method, path, headers=ADMIN, json=body).status_code == code
    assert log.records == []


def test_disable_and_enable_are_recorded(setup):
    client, fake, log = setup
    assert client.post("/admin/users/u1/disable", headers=ADMIN).status_code == 204
    assert fake.users["u1"]["enabled"] is False
    assert client.post("/admin/users/u1/enable", headers=ADMIN).status_code == 204
    assert [(r.action, r.old_value, r.new_value) for r in log.records] == [
        ("user_enabled", "true", "false"), ("user_enabled", "false", "true"),
    ]


def test_only_an_admin_manages_users(setup):
    client, _, _ = setup
    assert client.get("/admin/users", headers=VIEWER).status_code == 403
