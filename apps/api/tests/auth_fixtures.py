"""Test signing keys and a JWKS endpoint that serves them."""

import json

from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

JWKS_URL = "https://idp.example.com/certs"


class SigningKey:
    def __init__(self, kid: str):
        self.kid = kid
        self.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def jwk(self) -> dict:
        return {**json.loads(RSAAlgorithm.to_jwk(self.private.public_key())), "kid": self.kid, "use": "sig", "alg": "RS256"}


KEY = SigningKey("key-1")


class FakeJwks:
    """The JWKS endpoint: serves ``keys`` and counts its fetches."""

    def __init__(self, *keys: SigningKey):
        self.keys = list(keys)
        self.fetches = 0

    def __call__(self, url: str) -> dict:
        assert url == JWKS_URL
        self.fetches += 1
        return {"keys": [key.jwk() for key in self.keys]}
