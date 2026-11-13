"""Sign-in through one OpenID Connect provider in team mode (DECISIONS §9).

The authorization-code flow with PKCE (S256), a random ``state`` and a
``nonce``. ``start`` stores the state with its verifier, nonce and redirect URI
for ten minutes and returns the provider's authorization URL; ``finish`` takes
the state once, exchanges the code with the client secret (HTTP Basic), and
accepts the ID token only when it is signed by a key of the provider's JWKS
(read through the JWKS cache of ``app/auth/jwt.py``), issued by the configured
issuer for this client, unexpired and carrying the nonce.

The first sign-in of a subject creates an account with the roles named by the
configured claim that exist in the instance, or none; later sign-ins find the
same account and leave its roles to the Users page. An e-mail that another
account already uses is refused, so a provider cannot take over a local account.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
import base64
import hashlib
import secrets
import threading
import time
from urllib.parse import urlencode

import httpx
import jwt

from app.auth import accounts
from app.auth.jwt import AuthError, AuthUnavailable, JwksCache
from app.state.db import StateDb

LOGIN_TTL_SECONDS = 10 * 60
TIMEOUT_SECONDS = 10
ALGORITHMS = ["RS256", "RS384", "RS512", "PS256", "ES256", "ES384"]
SCOPES = "openid email profile"

Clock = Callable[[], float]


class OidcError(Exception):
    """The provider or its answer cannot be used; the sign-in fails."""


@dataclass(frozen=True)
class OidcConfig:
    issuer: str
    client_id: str
    client_secret: str
    roles_claim: str


class Provider:
    """One provider: its discovery document and JWKS are read once and reused."""

    def __init__(self, config: OidcConfig, http: httpx.Client):
        self.config = config
        self._http = http
        self._discovery: dict | None = None
        self._jwks: JwksCache | None = None
        self._lock = threading.Lock()

    def _get_json(self, url: str) -> dict:
        try:
            response = self._http.get(url, timeout=TIMEOUT_SECONDS)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise OidcError(f"the provider did not answer {url}: {type(error).__name__}") from None

    def discovery(self) -> dict:
        with self._lock:
            if self._discovery is None:
                issuer = self.config.issuer.rstrip("/")
                document = self._get_json(f"{issuer}/.well-known/openid-configuration")
                if document.get("issuer", "").rstrip("/") != issuer:
                    raise OidcError("the provider's discovery document names another issuer")
                missing = [key for key in ("authorization_endpoint", "token_endpoint", "jwks_uri") if not document.get(key)]
                if missing:
                    raise OidcError(f"the provider's discovery document has no {', '.join(missing)}")
                self._discovery = document
                self._jwks = JwksCache(document["jwks_uri"], fetch=self._get_json)
            return self._discovery

    def authorization_url(self, state: str, nonce: str, challenge: str, redirect_uri: str) -> str:
        query = urlencode({
            "response_type": "code", "client_id": self.config.client_id, "redirect_uri": redirect_uri,
            "scope": SCOPES, "state": state, "nonce": nonce,
            "code_challenge": challenge, "code_challenge_method": "S256",
        })
        return f"{self.discovery()['authorization_endpoint']}?{query}"

    def id_token_claims(self, code: str, verifier: str, redirect_uri: str, nonce: str) -> dict:
        document = self.discovery()
        try:
            response = self._http.post(
                document["token_endpoint"], timeout=TIMEOUT_SECONDS,
                auth=(self.config.client_id, self.config.client_secret),
                data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
                      "code_verifier": verifier},
            )
        except httpx.HTTPError as error:
            raise OidcError(f"the provider's token endpoint did not answer: {type(error).__name__}") from None
        if response.status_code != 200:
            raise OidcError(f"the provider refused the code (HTTP {response.status_code})")
        token = response.json().get("id_token")
        if not isinstance(token, str):
            raise OidcError("the provider returned no ID token")
        return self._verify(token, nonce)

    def _verify(self, token: str, nonce: str) -> dict:
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") not in ALGORITHMS or not header.get("kid"):
                raise OidcError("the ID token's algorithm or key id is not accepted")
            key = self._jwks.key(header["kid"])
            claims = jwt.decode(
                token, key.key, algorithms=ALGORITHMS, audience=self.config.client_id,
                issuer=self.config.issuer.rstrip("/"), options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except (jwt.InvalidTokenError, AuthError) as error:
            raise OidcError(f"the ID token was refused: {error}") from None
        except AuthUnavailable as error:
            raise OidcError(str(error)) from None
        if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
            raise OidcError("the ID token carries another nonce")
        return claims


def _challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def start(db: StateDb, provider: Provider, redirect_uri: str, clock: Clock = time.time) -> str:
    """Remember a new sign-in and return the provider URL to send the browser to."""
    state, verifier, nonce = (secrets.token_urlsafe(32) for _ in range(3))
    url = provider.authorization_url(state, nonce, _challenge(verifier), redirect_uri)
    now = clock()
    with db.write() as conn:
        conn.execute("DELETE FROM oidc_logins WHERE created_at <= ?", (now - LOGIN_TTL_SECONDS,))
        conn.execute("INSERT INTO oidc_logins (state, verifier, nonce, redirect_uri, created_at) VALUES (?, ?, ?, ?, ?)",
                     (state, verifier, nonce, redirect_uri, now))
    return url


def _roles(claims: dict, claim: str, instance_roles: Iterable[str]) -> list[str]:
    value = claims.get(claim)
    named = [value] if isinstance(value, str) else [item for item in value if isinstance(item, str)] if isinstance(value, list) else []
    known = set(instance_roles)
    return [role for role in named if role in known]


def finish(
    db: StateDb, provider: Provider, state: str, code: str, instance_roles: Iterable[str], clock: Clock = time.time,
) -> accounts.Account:
    """The account a provider callback signs in, creating it on the subject's first sign-in."""
    with db.write() as conn:
        row = conn.execute("SELECT verifier, nonce, redirect_uri, created_at FROM oidc_logins WHERE state = ?",
                           (state,)).fetchone()
        conn.execute("DELETE FROM oidc_logins WHERE state = ?", (state,))
    if row is None or clock() - row[3] > LOGIN_TTL_SECONDS:
        raise OidcError("this sign-in is unknown or has expired; start again")
    verifier, nonce, redirect_uri, _ = row
    claims = provider.id_token_claims(code, verifier, redirect_uri, nonce)
    subject = f"{provider.config.issuer.rstrip('/')} {claims['sub']}"
    account = accounts.by_oidc_subject(db, subject)
    if account is None:
        email = claims.get("email")
        if not isinstance(email, str):
            raise OidcError("the provider shares no e-mail address; allow the email scope")
        try:
            if accounts.email_taken(db, email):
                raise OidcError("an account with this e-mail already exists; sign in with its password")
            account = accounts.create(db, email, str(claims.get("name") or email), None,
                                      _roles(claims, provider.config.roles_claim, instance_roles),
                                      oidc_subject=subject)
        except accounts.AccountError as error:
            raise OidcError(str(error)) from None
    if not account.enabled:
        raise OidcError("this account is disabled")
    return account
