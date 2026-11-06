"""Set the password of every lab user of the tracked Keycloak realm.

Run with ``docker compose run --rm jobs python -m jobs.set_lab_passwords``
after Keycloak has imported ``infra/keycloak/realm-finch.json``. The realm file
defines its users without credentials, so no password is ever committed; this
job signs in to the ``master`` realm as the bootstrap administrator
(``KEYCLOAK_ADMIN`` / ``KEYCLOAK_ADMIN_PASSWORD``) and gives each lab user the
permanent password ``KEYCLOAK_LAB_USER_PASSWORD`` from the local ``.env``. The
password is never printed. Keycloak runs on an in-container database, so
recreating the container re-imports the realm and this job runs again.
"""

from collections.abc import Mapping
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request

REALM_FILE = Path(__file__).resolve().parents[1] / "infra" / "keycloak" / "realm-finch.json"
TIMEOUT_SECONDS = 30


def lab_usernames() -> list[str]:
    realm = json.loads(REALM_FILE.read_text(encoding="utf-8"))
    # A client's service account signs in with its client secret, never a password.
    return [user["username"] for user in realm.get("users", []) if "serviceAccountClientId" not in user]


def realm_name() -> str:
    return json.loads(REALM_FILE.read_text(encoding="utf-8"))["realm"]


def call(method: str, url: str, body: dict | None = None, form: dict | None = None, token: str | None = None):
    """One Keycloak request; returns the decoded JSON body, or None when there is none."""
    headers = {}
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        payload = response.read()
    return json.loads(payload) if payload else None


def main(env: Mapping[str, str] | None = None) -> int:
    env = os.environ if env is None else env
    missing = [name for name in ("KEYCLOAK_ADMIN", "KEYCLOAK_ADMIN_PASSWORD", "KEYCLOAK_LAB_USER_PASSWORD") if not env.get(name)]
    if missing:
        print(f"{', '.join(missing)} must be set", file=sys.stderr)
        return 1
    base = env.get("KEYCLOAK_URL", "http://keycloak:8080").rstrip("/")
    realm = realm_name()
    try:
        token = call("POST", f"{base}/realms/master/protocol/openid-connect/token", form={
            "grant_type": "password", "client_id": "admin-cli",
            "username": env["KEYCLOAK_ADMIN"], "password": env["KEYCLOAK_ADMIN_PASSWORD"],
        })["access_token"]
        not_found = []
        for username in lab_usernames():
            query = urllib.parse.urlencode({"username": username, "exact": "true"})
            users = call("GET", f"{base}/admin/realms/{realm}/users?{query}", token=token)
            if not users:
                not_found.append(username)
                continue
            call("PUT", f"{base}/admin/realms/{realm}/users/{users[0]['id']}/reset-password", token=token, body={
                "type": "password", "value": env["KEYCLOAK_LAB_USER_PASSWORD"], "temporary": False,
            })
            print(f"Set the password of {username}")
    except urllib.error.HTTPError as error:
        print(f"Keycloak returned HTTP {error.code} for {error.url}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, TimeoutError) as error:
        print(f"Keycloak at {base} is not reachable: {type(error).__name__}", file=sys.stderr)
        return 1
    if not_found:
        print(f"Users missing from realm {realm}: {', '.join(not_found)}; recreate Keycloak to re-import it", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
