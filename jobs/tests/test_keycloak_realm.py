"""The tracked Keycloak realm: pack roles, console roles, lab users without credentials, roles in tokens."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REALM = json.loads((ROOT / "infra" / "keycloak" / "realm-finch.json").read_text(encoding="utf-8"))
CONSOLE_ROLES = {"pack_reviewer", "admin"}


def _active_pack_roles() -> set[str]:
    import sys

    sys.path.insert(0, str(ROOT / "apps" / "api"))
    from app.packs.loader import read_yaml

    active = next(
        line.split("=", 1)[1].strip()
        for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
        if line.startswith("ACTIVE_PACK=")
    )
    return {role["id"] for role in read_yaml(ROOT / "packs" / active / "policies.yaml")["roles"]}


def test_realm_roles_are_the_active_packs_policy_roles_and_the_console_roles():
    realm_roles = {role["name"] for role in REALM["roles"]["realm"]}

    assert realm_roles == _active_pack_roles() | CONSOLE_ROLES


def test_every_lab_user_has_known_roles_and_no_credentials():
    realm_roles = {role["name"] for role in REALM["roles"]["realm"]}
    users = REALM["users"]

    assert users
    for user in users:
        assert "credentials" not in user, user["username"]
        assert user["enabled"] is True
        assert set(user["realmRoles"]) <= realm_roles, user["username"]


def test_every_role_has_a_lab_user():
    granted = {role for user in REALM["users"] for role in user["realmRoles"]}

    assert granted == {role["name"] for role in REALM["roles"]["realm"]}


def test_web_client_access_tokens_carry_the_realm_roles():
    client = next(client for client in REALM["clients"] if client["clientId"] == "finch-web")

    assert "roles" in client["defaultClientScopes"]
    assert client["publicClient"] is True and client["directAccessGrantsEnabled"] is False


def test_lab_users_can_sign_in_without_completing_a_profile():
    # Keycloak's user profile asks for a verified email before the first sign-in otherwise.
    for user in REALM["users"]:
        assert user["email"].endswith(".test") and user["emailVerified"] is True, user["username"]
        assert user["firstName"] and user["lastName"], user["username"]
        assert not user.get("requiredActions"), user["username"]


def _client(client_id: str) -> dict:
    return next(client for client in REALM["clients"] if client["clientId"] == client_id)


def test_web_and_cli_access_tokens_name_the_api_as_audience():
    for client_id in ("finch-web", "finch-cli"):
        audiences = [
            mapper["config"]["included.custom.audience"] for mapper in _client(client_id).get("protocolMappers", [])
            if mapper["protocolMapper"] == "oidc-audience-mapper" and mapper["config"]["access.token.claim"] == "true"
        ]
        assert audiences == ["finch-api"], client_id


def test_the_cli_client_only_grants_tokens_for_a_username_and_password():
    client = _client("finch-cli")

    assert client["publicClient"] is True and client["directAccessGrantsEnabled"] is True
    assert client["standardFlowEnabled"] is False and client["implicitFlowEnabled"] is False
    assert "roles" in client["defaultClientScopes"]


def test_the_web_client_redirects_only_to_its_sign_in_callback():
    assert _client("finch-web")["redirectUris"] == ["http://localhost:3000/auth/callback"]
