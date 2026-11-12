"""``jobs/set_lab_passwords.py`` with the Keycloak admin API replaced by a fake."""

import pytest

from jobs import set_lab_passwords as job

ENV = {
    "KEYCLOAK_URL": "http://keycloak:8080",
    "KEYCLOAK_ADMIN": "admin",
    "KEYCLOAK_ADMIN_PASSWORD": "admin-secret",
    "KEYCLOAK_LAB_USER_PASSWORD": "lab-secret",
}


class FakeKeycloak:
    """Answers the token, user search and password reset calls; records each call."""

    def __init__(self, users: dict[str, str]):
        self.users = users  # username -> id
        self.calls: list[tuple[str, str, dict | None]] = []

    def __call__(self, method: str, url: str, body: dict | None = None, form: dict | None = None, token: str | None = None):
        self.calls.append((method, url, body or form))
        if url.endswith("/realms/master/protocol/openid-connect/token"):
            assert form == {"grant_type": "password", "client_id": "admin-cli", "username": "admin", "password": "admin-secret"}
            return {"access_token": "admin-token"}
        assert token == "admin-token"
        if "/users?" in url:
            username = url.split("username=")[1].split("&")[0]
            return [{"id": self.users[username], "username": username}] if username in self.users else []
        if url.endswith("/reset-password"):
            return None
        raise AssertionError(url)


def test_sets_every_realm_users_password_as_permanent(monkeypatch, capsys):
    keycloak = FakeKeycloak({name: f"id-{name}" for name in job.lab_usernames()})
    monkeypatch.setattr(job, "call", keycloak)

    assert job.main(ENV) == 0

    resets = [(url, body) for method, url, body in keycloak.calls if url.endswith("/reset-password")]
    assert len(resets) == len(job.lab_usernames())
    assert all(body == {"type": "password", "value": "lab-secret", "temporary": False} for _, body in resets)
    assert all("/admin/realms/finch/users/id-" in url for url, _ in resets)
    assert "lab-secret" not in capsys.readouterr().out


def test_missing_lab_password_fails_before_any_call(monkeypatch, capsys):
    keycloak = FakeKeycloak({})
    monkeypatch.setattr(job, "call", keycloak)

    assert job.main({**ENV, "KEYCLOAK_LAB_USER_PASSWORD": ""}) == 1

    assert keycloak.calls == []
    assert "KEYCLOAK_LAB_USER_PASSWORD" in capsys.readouterr().err


def test_user_missing_from_keycloak_is_reported(monkeypatch, capsys):
    names = job.lab_usernames()
    keycloak = FakeKeycloak({name: f"id-{name}" for name in names[1:]})
    monkeypatch.setattr(job, "call", keycloak)

    assert job.main(ENV) == 1

    assert names[0] in capsys.readouterr().err


@pytest.mark.parametrize("missing", ["KEYCLOAK_ADMIN", "KEYCLOAK_ADMIN_PASSWORD"])
def test_admin_credentials_are_required(monkeypatch, missing):
    monkeypatch.setattr(job, "call", FakeKeycloak({}))

    assert job.main({**ENV, missing: ""}) == 1


def test_a_clients_service_account_never_gets_a_password():
    assert "service-account-fitcher-admin-api" not in job.lab_usernames()
    assert "lab.admin" in job.lab_usernames()
