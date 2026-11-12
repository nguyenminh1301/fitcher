"""The Keycloak Admin REST API as the ``fitcher-admin-api`` service account (DECISIONS §9, §15).

The account holds only ``realm-management`` ``view-users`` and ``manage-users``:
it lists users and their realm roles, maps realm roles and enables or disables
a user. It never creates or deletes users or sets credentials. A token is
fetched with the client-credentials grant and reused until shortly before it
expires. Role representations come from a user's available or effective role
mappings, so no realm-wide read right is needed.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import os
import time

import httpx

TIMEOUT_SECONDS = 15
EXPIRY_MARGIN_SECONDS = 30
PAGE = 200


class KeycloakAdminError(RuntimeError):
    """The Admin API refused a request or could not be reached."""


@dataclass(frozen=True)
class RealmUser:
    id: str
    username: str
    display_name: str
    enabled: bool
    roles: list[str]


class KeycloakAdmin:
    def __init__(self, base_url: str, realm: str, client_id: str, secret: str, http: httpx.Client | None = None,
                 clock: Callable[[], float] = time.monotonic):
        if not secret:
            raise KeycloakAdminError("KEYCLOAK_ADMIN_API_SECRET must be set")
        self._base = base_url.rstrip("/")
        self._realm = realm
        self._client_id = client_id
        self._secret = secret
        self._http = http or httpx.Client(timeout=TIMEOUT_SECONDS)
        self._clock = clock
        self._token: tuple[str, float] | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "KeycloakAdmin":
        env = os.environ if env is None else env
        return cls(env.get("KEYCLOAK_URL", "http://keycloak:8080"), env.get("KEYCLOAK_REALM", "finch"),
                   env.get("KEYCLOAK_ADMIN_API_CLIENT", "fitcher-admin-api"), env.get("KEYCLOAK_ADMIN_API_SECRET", ""))

    def _bearer(self) -> str:
        if self._token and self._token[1] > self._clock():
            return self._token[0]
        try:
            response = self._http.post(
                f"{self._base}/realms/{self._realm}/protocol/openid-connect/token",
                data={"grant_type": "client_credentials", "client_id": self._client_id, "client_secret": self._secret},
            )
        except httpx.HTTPError as error:
            raise KeycloakAdminError(f"Keycloak is unreachable: {type(error).__name__}") from None
        if response.status_code != 200:
            raise KeycloakAdminError(f"the admin API client was refused a token (HTTP {response.status_code})")
        body = response.json()
        self._token = (body["access_token"], self._clock() + float(body.get("expires_in", 60)) - EXPIRY_MARGIN_SECONDS)
        return self._token[0]

    def _call(self, method: str, path: str, **kwargs):
        try:
            response = self._http.request(method, f"{self._base}/admin/realms/{self._realm}{path}",
                                          headers={"Authorization": f"Bearer {self._bearer()}"}, **kwargs)
        except httpx.HTTPError as error:
            raise KeycloakAdminError(f"Keycloak is unreachable: {type(error).__name__}") from None
        if response.status_code == 404:
            raise KeycloakAdminError("user not found")
        if response.status_code >= 300:
            raise KeycloakAdminError(f"{method} {path} returned HTTP {response.status_code}")
        return response.json() if response.content else None

    def _roles(self, user_id: str) -> list[dict]:
        return self._call("GET", f"/users/{user_id}/role-mappings/realm") or []

    def users(self) -> list[RealmUser]:
        found = []
        for user in self._call("GET", "/users", params={"max": PAGE, "briefRepresentation": "true"}) or []:
            if user.get("username", "").startswith("service-account-"):
                continue
            name = " ".join(part for part in (user.get("firstName"), user.get("lastName")) if part) or user["username"]
            found.append(RealmUser(id=user["id"], username=user["username"], display_name=name,
                                   enabled=bool(user.get("enabled")), roles=sorted(r["name"] for r in self._roles(user["id"]))))
        return found

    def user(self, user_id: str) -> RealmUser:
        user = self._call("GET", f"/users/{user_id}")
        name = " ".join(part for part in (user.get("firstName"), user.get("lastName")) if part) or user["username"]
        return RealmUser(id=user["id"], username=user["username"], display_name=name, enabled=bool(user.get("enabled")),
                         roles=sorted(role["name"] for role in self._roles(user_id)))

    def set_roles(self, user_id: str, add: set[str], remove: set[str]) -> None:
        if remove:
            current = [role for role in self._roles(user_id) if role["name"] in remove]
            if current:
                self._call("DELETE", f"/users/{user_id}/role-mappings/realm", json=current)
        if add:
            available = self._call("GET", f"/users/{user_id}/role-mappings/realm/available") or []
            wanted = [role for role in available if role["name"] in add]
            if len(wanted) != len(add):
                missing = sorted(add - {role["name"] for role in wanted})
                raise KeycloakAdminError(f"the realm has no assignable role {', '.join(missing)}")
            self._call("POST", f"/users/{user_id}/role-mappings/realm", json=wanted)

    def set_enabled(self, user_id: str, enabled: bool) -> None:
        self._call("PUT", f"/users/{user_id}", json={"enabled": enabled})
