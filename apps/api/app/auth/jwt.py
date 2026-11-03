"""Verify Keycloak access tokens (DECISIONS §2 and §9).

A token is accepted only when it is an RS256 JWT signed by a key of the realm's
JWKS, issued by ``KEYCLOAK_ISSUER`` for the audience ``KEYCLOAK_AUDIENCE``,
not expired, and names its subject. The JWKS is fetched once and cached; a
token whose ``kid`` the cache does not know refreshes it, at most once per
``min_refresh_seconds``, so a stream of forged key ids cannot hammer Keycloak.
"""

from collections.abc import Callable
from dataclasses import dataclass
import threading
import time

import httpx
import jwt

ALGORITHMS = ["RS256"]
FETCH_TIMEOUT_SECONDS = 5.0
REQUIRED_CLAIMS = ["exp", "iat", "iss", "aud", "sub"]


class AuthError(Exception):
    """The token is missing, malformed or fails a check; the request is unauthorized."""


class AuthUnavailable(Exception):
    """The keys cannot be read, so no token can be checked."""


@dataclass(frozen=True)
class TokenSettings:
    issuer: str
    audience: str
    jwks_url: str


@dataclass(frozen=True)
class Principal:
    """The verified user: ``user_id`` is the username, which agent_logs record, else the subject."""

    user_id: str
    subject: str
    display_name: str
    roles: tuple[str, ...]


def fetch_json(url: str) -> dict:
    response = httpx.get(url, timeout=FETCH_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


class JwksCache:
    def __init__(
        self, url: str, fetch: Callable[[str], dict] = fetch_json, *,
        min_refresh_seconds: float = 30.0, clock: Callable[[], float] = time.monotonic,
    ):
        self._url = url
        self._fetch = fetch
        self._min_refresh = min_refresh_seconds
        self._clock = clock
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched_at: float | None = None
        self._lock = threading.Lock()

    def _refresh(self) -> None:
        try:
            document = self._fetch(self._url)
        except Exception as error:  # noqa: BLE001 - any fetch failure leaves no key to check with
            raise AuthUnavailable(f"cannot read the JWKS: {type(error).__name__}") from error
        self._fetched_at = self._clock()
        keys = {}
        for item in document.get("keys", []):
            if item.get("kid") and item.get("use", "sig") == "sig":
                try:
                    keys[item["kid"]] = jwt.PyJWK(item)
                except jwt.PyJWKError:
                    continue
        self._keys = keys

    def key(self, kid: str) -> jwt.PyJWK:
        with self._lock:
            if kid not in self._keys:
                due = self._fetched_at is None or self._clock() - self._fetched_at >= self._min_refresh
                if due:
                    self._refresh()
            if kid not in self._keys:
                raise AuthError(f"no signing key {kid!r} in the JWKS")
            return self._keys[kid]


class TokenVerifier:
    def __init__(self, settings: TokenSettings, jwks: JwksCache):
        self._settings = settings
        self._jwks = jwks

    def verify(self, token: str) -> Principal:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError as error:
            raise AuthError(f"malformed token: {error}") from None
        if header.get("alg") not in ALGORITHMS:
            raise AuthError(f"algorithm {header.get('alg')!r} is not accepted")
        kid = header.get("kid")
        if not kid:
            raise AuthError("the token names no signing key")
        key = self._jwks.key(kid)
        try:
            claims = jwt.decode(
                token, key.key, algorithms=ALGORITHMS, audience=self._settings.audience,
                issuer=self._settings.issuer, options={"require": REQUIRED_CLAIMS},
            )
        except jwt.ExpiredSignatureError:
            raise AuthError("the token has expired") from None
        except jwt.InvalidTokenError as error:
            raise AuthError(f"the token was refused: {error}") from None
        realm_roles = claims.get("realm_access", {}).get("roles", [])
        subject = claims["sub"]
        user_id = claims.get("preferred_username") or subject
        return Principal(
            user_id=user_id, subject=subject, display_name=claims.get("name") or user_id,
            roles=tuple(role for role in realm_roles if isinstance(role, str)),
        )
