"""Long-lived objects the endpoints share, built on first use from the environment.

Each is a FastAPI dependency, so tests override it. A missing setting or an
uncompiled pack makes the endpoints that need it answer 503, while ``/health``
keeps working; a failure is not cached, so the next request tries again.
"""

from functools import cache
from pathlib import Path

from fastapi import HTTPException, status

from app.auth.jwt import JwksCache, TokenSettings, TokenVerifier
from app.config import load_settings
from app.packs.compiler import CompileError, CompiledPack, load_compiled


def unavailable(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail)


@cache
def get_verifier() -> TokenVerifier:
    settings = load_settings()
    token = TokenSettings(settings.keycloak_issuer, settings.keycloak_audience, settings.keycloak_jwks_url)
    if not all((token.issuer, token.audience, token.jwks_url)):
        raise unavailable("KEYCLOAK_ISSUER, KEYCLOAK_AUDIENCE and KEYCLOAK_JWKS_URL must be set")
    return TokenVerifier(token, JwksCache(token.jwks_url))


@cache
def get_compiled() -> CompiledPack:
    settings = load_settings()
    if not settings.active_pack:
        raise unavailable("ACTIVE_PACK must be set")
    try:
        return load_compiled(Path(settings.compiled_pack_dir), settings.active_pack)
    except CompileError as error:
        raise unavailable(str(error)) from None
