"""Long-lived objects the endpoints share, built on first use from the environment.

Each is a FastAPI dependency, so tests override it. A missing setting or an
uncompiled pack makes the endpoints that need it answer 503, while ``/health``
keeps working; a failure is not cached, so the next request tries again.
"""

from dataclasses import dataclass
from functools import cache
import logging
from pathlib import Path
import threading

import yaml

from typing import Annotated

from fastapi import Depends, HTTPException, status

from app.api.agent import Agent
from app.api.rate_limit import RateLimiter
from app.auth.jwt import JwksCache, TokenSettings, TokenVerifier
from app.config import load_settings
from app.conversation.store import ConversationStore, conversations_client
from app.data.clickhouse import ClientWarehouse, QueryLimits
from app.llm.client import LiteLLMClient, LLMError
from app.llm.embeddings import LiteLLMEmbeddings
from app.llm.model_store import CatalogClient, ClickHouseModelStore, model_tiers_client
from app.llm.tiers import EMBED_TIER, TierMap, TierStoreError
from app.onboarding.documents import ClickHouseDocumentRegistry, DocumentService, pack_review_client
from app.onboarding.drafter import Drafter
from app.onboarding.review import ReviewService
from app.packs.compiler import CompileError, CompiledPack, load_compiled
from app.screening.screen import Screener
from app.search.client import QdrantSearch


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


def get_compiled_or_none() -> CompiledPack | None:
    """The compiled active pack, or None while it was never compiled (a pack still under onboarding)."""
    try:
        return get_compiled()
    except HTTPException:
        return None


@dataclass(frozen=True)
class PackIdentity:
    name: str
    display_name: str
    # The pack's policy roles, in policies.yaml order.
    roles: list[str]


def _read(path: Path) -> dict:
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}) if path.is_file() else {}


def pack_identity(compiled: CompiledPack | None) -> PackIdentity:
    """Name, display name and roles of the active pack: from ``compiled.json``, else from its pack files.

    A new company's pack is reviewed before its first compile, so sign-in, Review and Documents read the
    pack files until ``compile_pack`` has run; questions still need the compiled pack.
    """
    if compiled is not None:
        return PackIdentity(
            compiled.pack.name, compiled.pack.business_profile.display_name,
            [role.id for role in compiled.pack.policies.roles],
        )
    settings = load_settings()
    if not settings.active_pack:
        raise unavailable("ACTIVE_PACK must be set")
    pack_dir = Path(settings.packs_dir) / settings.active_pack
    if not (pack_dir / "policies.yaml").is_file():
        raise unavailable(
            f"pack {settings.active_pack} has no compiled.json and no pack files under {settings.packs_dir}; "
            "compile the pack first"
        )
    profile = _read(pack_dir / "business_profile.yaml")
    roles = [role["id"] for role in _read(pack_dir / "policies.yaml").get("roles") or [] if isinstance(role, dict)]
    return PackIdentity(settings.active_pack, str(profile.get("display_name") or settings.active_pack), roles)


def get_pack_identity(compiled: Annotated[CompiledPack | None, Depends(get_compiled_or_none)]) -> PackIdentity:
    return pack_identity(compiled)


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
def get_model_store() -> ClickHouseModelStore:
    try:
        return ClickHouseModelStore(model_tiers_client())
    except Exception as error:  # noqa: BLE001 - a missing password or unreachable ClickHouse
        raise unavailable(f"the model store is unavailable: {error}") from None


class LazyTierStore:
    """The model store, looked up on every read: a store unavailable at startup is used once it is back."""

    def read(self) -> dict[str, str]:
        try:
            store = get_model_store()
        except HTTPException as error:
            raise TierStoreError(str(error.detail)) from None
        return store.read()

    def write(self, tier, alias, changed_by, changed_at) -> None:
        get_model_store().write(tier, alias, changed_by, changed_at)


@cache
def get_tier_map() -> TierMap:
    """The process's tier lookup; while the model store is unavailable, every tier keeps its default."""
    return TierMap(load_settings().model_tiers, LazyTierStore())


@cache
def get_catalog() -> CatalogClient:
    settings = load_settings()
    return CatalogClient(settings.litellm_base_url, settings.litellm_master_key)


@cache
def get_agent() -> Agent:
    try:
        return Agent(load_settings(), get_compiled(), get_screener(), get_tier_map())
    except LLMError as error:
        raise unavailable(str(error)) from None


@cache
def get_conversation_store() -> ConversationStore:
    try:
        return ConversationStore(conversations_client())
    except RuntimeError as error:
        raise unavailable(str(error)) from None


@cache
def get_document_service() -> DocumentService:
    """The active pack's documents; chunks are screened and embedded like a compile does."""
    settings = load_settings()
    identity = pack_identity(get_compiled_or_none())
    try:
        registry = ClickHouseDocumentRegistry(pack_review_client())
        embeddings = LiteLLMEmbeddings(
            settings.litellm_base_url, settings.litellm_master_key, settings.embedding_dimensions,
            alias=settings.model_tiers[EMBED_TIER],
        )
    except Exception as error:  # noqa: BLE001 - a missing password or gateway key, or ClickHouse unreachable
        raise unavailable(f"the document store is unavailable: {error}") from None
    return DocumentService(
        pack=identity.name, pack_roles=identity.roles, registry=registry,
        search=QdrantSearch(settings.qdrant_url), embeddings=embeddings, screener=get_screener(),
        store_dir=Path(settings.documents_dir), compiled_dir=Path(settings.compiled_pack_dir),
        max_bytes=settings.document_max_bytes,
    )


def get_pack_dir() -> Path:
    """The active pack's working tree, where reviewed and drafted YAML is written (never committed by the app)."""
    return Path(load_settings().packs_dir) / pack_identity(get_compiled_or_none()).name


@cache
def get_review_warehouse() -> ClientWarehouse:
    """Reads marts as ``pack_review`` for drafts and reviewer test-runs; each query sends its own limits."""
    try:
        return ClientWarehouse(pack_review_client())
    except Exception as error:  # noqa: BLE001 - a missing password or ClickHouse unreachable
        raise unavailable(f"the warehouse is unavailable: {error}") from None


@cache
def get_drafter() -> Drafter:
    settings = load_settings()
    try:
        llm = LiteLLMClient(settings.litellm_base_url, settings.litellm_master_key, tiers=get_tier_map())
    except LLMError as error:
        raise unavailable(str(error)) from None
    return Drafter(llm, get_review_warehouse())


def get_review_service() -> ReviewService:
    """Built per request: it reads the pack files fresh each time."""
    settings = load_settings()
    return ReviewService(
        pack=pack_identity(get_compiled_or_none()).name, pack_dir=get_pack_dir(), registry=get_document_service().registry,
        warehouse=get_review_warehouse(), limits=QueryLimits.from_env(), compiled_dir=Path(settings.compiled_pack_dir),
    )


@cache
def get_rate_limiter() -> RateLimiter:
    return RateLimiter(load_settings().rate_limit_per_minute)


def close() -> None:
    """Flush and stop the agent's log writer if a question ever built the agent."""
    if get_agent.cache_info().currsize:
        get_agent().close()
