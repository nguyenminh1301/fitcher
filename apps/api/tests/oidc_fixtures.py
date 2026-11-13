"""A fake OpenID Connect provider over httpx.MockTransport: discovery, JWKS and the token endpoint."""

import base64
import hashlib
import time
from urllib.parse import parse_qs

import httpx
import jwt

from auth_fixtures import SigningKey

ISSUER = "https://idp.example.com/realms/acme"
CLIENT_ID = "fitcher"
CLIENT_SECRET = "client-secret-1234"


class FakeProvider:
    """Issues an ID token for the next authorization code; ``claims`` and ``key`` shape it."""

    def __init__(self):
        self.key = SigningKey("idp-key")
        # The key the JWKS publishes; a test sets another one to sign with a key the provider never published.
        self.published = self.key
        self.claims: dict = {"sub": "user-42", "email": "Carol@Example.com", "name": "Carol", "groups": ["viewer", "unknown_role"]}
        self.codes: dict[str, dict] = {}
        self.token_requests: list[dict] = []
        self.discovery_fetches = 0

    def issue_code(self, nonce: str, challenge: str, redirect_uri: str) -> str:
        code = f"code-{len(self.codes)}"
        self.codes[code] = {"nonce": nonce, "challenge": challenge, "redirect_uri": redirect_uri}
        return code

    def id_token(self, issued_nonce: str, /, **overrides) -> str:
        now = int(time.time())
        claims = {"iss": ISSUER, "aud": CLIENT_ID, "iat": now, "exp": now + 300, "nonce": issued_nonce, **self.claims,
                  **overrides}
        claims = {key: value for key, value in claims.items() if value is not None}
        return jwt.encode(claims, self.key.private, algorithm="RS256", headers={"kid": self.key.kid})

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/realms/acme/.well-known/openid-configuration":
            self.discovery_fetches += 1
            return httpx.Response(200, json={
                "issuer": ISSUER,
                "authorization_endpoint": f"{ISSUER}/protocol/openid-connect/auth",
                "token_endpoint": f"{ISSUER}/protocol/openid-connect/token",
                "jwks_uri": f"{ISSUER}/protocol/openid-connect/certs",
            })
        if path == "/realms/acme/protocol/openid-connect/certs":
            return httpx.Response(200, json={"keys": [self.published.jwk()]})
        if path == "/realms/acme/protocol/openid-connect/token":
            form = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
            self.token_requests.append({**form, "authorization": request.headers.get("authorization")})
            issued = self.codes.pop(form.get("code", ""), None)
            verifier = form.get("code_verifier", "")
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            if issued is None or issued["challenge"] != challenge or issued["redirect_uri"] != form.get("redirect_uri"):
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"access_token": "at", "token_type": "Bearer", "id_token": self.id_token(issued["nonce"])})
        return httpx.Response(404)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))
