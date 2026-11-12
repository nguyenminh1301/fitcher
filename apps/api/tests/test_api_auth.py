"""Bearer authentication and role mapping on the HTTP endpoints."""

from agent_fixtures import compiled_fixture
from auth_fixtures import token, verifier
from fastapi.testclient import TestClient
import pytest

from app.api import runtime
from app.main import app


@pytest.fixture
def client():
    app.dependency_overrides[runtime.get_verifier] = lambda: verifier()
    app.dependency_overrides[runtime.get_compiled] = compiled_fixture
    app.dependency_overrides[runtime.get_compiled_or_none] = compiled_fixture
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def bearer(text: str) -> dict:
    return {"Authorization": f"Bearer {text}"}


def test_me_returns_the_verified_user_and_active_role(client):
    response = client.get("/me", headers=bearer(token()))

    assert response.status_code == 200
    assert response.json() == {
        "user_id": "lab.viewer", "display_name": "Lab Viewer", "roles": ["viewer"], "active_role": "viewer",
    }


def test_a_missing_token_is_unauthorized(client):
    response = client.get("/me")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("header", ["Basic abc", "Bearer", "Bearer not-a-token", "token-without-scheme"])
def test_a_malformed_authorization_header_is_unauthorized(client, header):
    assert client.get("/me", headers={"Authorization": header}).status_code == 401


@pytest.mark.parametrize("overrides", [{"exp": 1_000_000}, {"iss": "http://other.test"}, {"aud": "other"}])
def test_an_invalid_token_is_unauthorized_without_detail_of_the_check(client, overrides):
    response = client.get("/me", headers=bearer(token(**overrides)))

    assert response.status_code == 401
    assert response.json() == {"detail": "invalid or expired access token"}


def test_a_user_without_a_pack_role_has_no_active_role(client):
    response = client.get("/me", headers=bearer(token(realm_access={"roles": ["admin"]})))

    assert response.status_code == 200
    assert response.json()["roles"] == ["admin"]
    assert response.json()["active_role"] is None


def test_an_active_role_header_the_token_does_not_hold_is_forbidden(client):
    response = client.get("/me", headers={**bearer(token()), "X-Active-Role": "auditor"})

    assert response.status_code == 403


def test_pack_names_the_active_pack_and_its_roles_without_a_token(client):
    response = client.get("/pack")

    assert response.status_code == 200
    pack = compiled_fixture().pack
    assert response.json() == {
        "name": pack.name, "display_name": pack.business_profile.display_name,
        "roles": [role.id for role in pack.policies.roles],
    }


def test_a_pack_under_onboarding_signs_in_from_its_pack_files(client, monkeypatch, tmp_path):
    from conftest import FIXTURE_PACK

    del app.dependency_overrides[runtime.get_compiled_or_none]
    runtime.get_compiled.cache_clear()
    monkeypatch.setenv("ACTIVE_PACK", "minimal")
    monkeypatch.setenv("COMPILED_PACK_DIR", str(tmp_path / "build"))
    monkeypatch.setenv("PACKS_DIR", str(FIXTURE_PACK.parent))

    assert client.get("/pack").json() == {"name": "minimal", "display_name": "Minimal widget shop", "roles": ["viewer"]}
    me = client.get("/me", headers=bearer(token(realm_access={"roles": ["viewer", "pack_reviewer"]}))).json()
    assert me["roles"] == ["viewer", "pack_reviewer"] and me["active_role"] == "viewer"


def test_an_uncompiled_pack_makes_the_endpoints_unavailable(client, monkeypatch, tmp_path):
    del app.dependency_overrides[runtime.get_compiled]
    del app.dependency_overrides[runtime.get_compiled_or_none]
    runtime.get_compiled.cache_clear()
    monkeypatch.setenv("ACTIVE_PACK", "demo")
    monkeypatch.setenv("COMPILED_PACK_DIR", str(tmp_path))
    monkeypatch.setenv("PACKS_DIR", str(tmp_path / "packs"))

    response = client.get("/pack")

    assert response.status_code == 503
    assert "compile the pack first" in response.json()["detail"]
    assert client.get("/me", headers=bearer(token())).status_code == 503
    runtime.get_compiled.cache_clear()


def test_unconfigured_token_settings_make_authenticated_endpoints_unavailable(client, monkeypatch):
    del app.dependency_overrides[runtime.get_verifier]
    runtime.get_verifier.cache_clear()
    for name in ("KEYCLOAK_ISSUER", "KEYCLOAK_AUDIENCE", "KEYCLOAK_JWKS_URL"):
        monkeypatch.delenv(name, raising=False)

    response = client.get("/me", headers=bearer(token()))

    assert response.status_code == 503
    runtime.get_verifier.cache_clear()
