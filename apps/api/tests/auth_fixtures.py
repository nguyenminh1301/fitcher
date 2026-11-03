"""Signed test tokens and the JWKS that serves their key, in place of Keycloak."""

import json
import time

from cryptography.hazmat.primitives.asymmetric import rsa
import jwt
from jwt.algorithms import RSAAlgorithm

from app.auth.jwt import JwksCache, TokenSettings, TokenVerifier

ISSUER = "http://keycloak.test/realms/lab"
AUDIENCE = "fitcher-api"
JWKS_URL = "http://keycloak.test/realms/lab/protocol/openid-connect/certs"
SETTINGS = TokenSettings(issuer=ISSUER, audience=AUDIENCE, jwks_url=JWKS_URL)


class SigningKey:
    def __init__(self, kid: str):
        self.kid = kid
        self.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def jwk(self) -> dict:
        return {**json.loads(RSAAlgorithm.to_jwk(self.private.public_key())), "kid": self.kid, "use": "sig", "alg": "RS256"}


KEY = SigningKey("key-1")


def claims(**overrides) -> dict:
    now = int(time.time())
    base = {
        "iss": ISSUER, "aud": AUDIENCE, "sub": "user-1", "iat": now, "exp": now + 300,
        "preferred_username": "lab.viewer", "name": "Lab Viewer",
        "realm_access": {"roles": ["viewer", "default-roles-lab", "offline_access"]},
    }
    return {key: value for key, value in {**base, **overrides}.items() if value is not None}


def token(key: SigningKey = KEY, **overrides) -> str:
    return jwt.encode(claims(**overrides), key.private, algorithm="RS256", headers={"kid": key.kid})


class FakeJwks:
    """The JWKS endpoint: serves ``keys`` and counts its fetches."""

    def __init__(self, *keys: SigningKey):
        self.keys = list(keys)
        self.fetches = 0

    def __call__(self, url: str) -> dict:
        assert url == JWKS_URL
        self.fetches += 1
        return {"keys": [key.jwk() for key in self.keys]}


def verifier(jwks: FakeJwks | None = None, **cache_options) -> TokenVerifier:
    return TokenVerifier(SETTINGS, JwksCache(JWKS_URL, fetch=jwks or FakeJwks(KEY), **cache_options))
