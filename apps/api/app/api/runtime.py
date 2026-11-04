"""Long-lived objects the endpoints share, built on first use from the environment.

Each is a FastAPI dependency, so tests override it. A missing setting or an
uncompiled pack makes the endpoints that need it answer 503, while ``/health``
keeps working; a failure is not cached, so the next request tries again.
"""

from functools import cache
import logging
from pathlib import Path
import threading

from fastapi import HTTPException, status

from app.api.agent import Agent
from app.api.rate_limit import RateLimiter
from app.auth.jwt import JwksCache, TokenSettings, TokenVerifier
from app.config import load_settings
from app.conversation.store import ConversationStore, conversations_client
from app.llm.client import LLMError
from app.packs.compiler import CompileError, CompiledPack, load_compiled
from app.screening.screen import Screener


logger = logging.getLogger(__name__)


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


_screener: Screener | None = None
_screener_lock = threading.Lock()


def get_screener() -> Screener:
    """The question screener, built once; without its model in ``GUARD_MODEL_DIR`` every question is refused.

    Building it loads the classifier, which takes seconds, so the api builds it in the background at startup.
    """
    global _screener
    with _screener_lock:
        if _screener is None:
            _screener = Screener.from_settings(load_settings())
        return _screener


def loaded_screener() -> Screener | None:
    """The screener if it is built; never builds it, so ``/health`` stays fast."""
    return _screener


def _build_screener() -> None:
    try:
        get_screener()
    except Exception:  # noqa: BLE001 - invalid settings leave screening unavailable; the next question tries again
        logger.exception("cannot build the question screener")


def build_screener_in_background() -> None:
    threading.Thread(target=_build_screener, name="screener", daemon=True).start()


@cache
def get_agent() -> Agent:
    try:
        return Agent(load_settings(), get_compiled(), get_screener())
    except LLMError as error:
        raise unavailable(str(error)) from None


@cache
def get_conversation_store() -> ConversationStore:
    try:
        return ConversationStore(conversations_client())
    except RuntimeError as error:
        raise unavailable(str(error)) from None


@cache
def get_rate_limiter() -> RateLimiter:
    return RateLimiter(load_settings().rate_limit_per_minute)


def close() -> None:
    """Flush and stop the agent's log writer if a question ever built the agent."""
    if get_agent.cache_info().currsize:
        get_agent().close()
