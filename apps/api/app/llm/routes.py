"""Which model of which provider serves each tier, and the gateway's resolver over it (DECISIONS §2).

The mapping lives in the app state: setting group ``llm.tiers`` holds
``{"provider_id", "model"}`` per chat tier, and ``llm.embedding`` the embed
tier's provider, model and vector size. Any model of a configured provider may
serve a chat tier; an eval result informs the choice and no longer gates it.
Adding the first provider fills every unmapped chat tier, and the embedding
when it is unset, from ``defaults``.

``SettingsRoutes`` reads the mapping on every call, so a change applies to the
next call in every process that shares the app state.

When no provider exists yet, ``bootstrap_from_env`` creates one per provider
setting of the environment (``OPENAI_API_KEY``, ``ANTHROPIC_API_KEY``,
``GEMINI_API_KEY``, ``OLLAMA_URL``) and maps the tiers to the first, so a
scripted start or CI needs no setup step. The embedding keeps
``EMBEDDING_DIMENSIONS`` so packs indexed before the app state existed still
match their vectors.
"""

from collections.abc import Mapping
from dataclasses import dataclass
import logging
import os

from app.llm import defaults
from app.llm.gateway import Route
from app.llm.providers import Provider, ProviderStore
from app.llm.tiers import check_chat_tier, CHAT_TIERS, EMBED_TIER
from app.state.db import shared_state, StateDb
from app.state.secrets import SecretError, SecretReader, shared_vault
from app.state.settings import Settings

TIERS_GROUP = "llm.tiers"
EMBEDDING_GROUP = "llm.embedding"
DEFAULT_DIMENSIONS = 1024
# The order in which environment providers are created; the first one maps the tiers.
ENV_PROVIDERS = (
    ("openai", "OPENAI_API_KEY", "api_key"),
    ("anthropic", "ANTHROPIC_API_KEY", "api_key"),
    ("gemini", "GEMINI_API_KEY", "api_key"),
    ("ollama", "OLLAMA_URL", "base_url"),
)


_log = logging.getLogger(__name__)


class RouteError(LookupError):
    """No model is mapped to the tier."""


@dataclass(frozen=True)
class TierModel:
    provider_id: str
    model: str


class TierMapping:
    def __init__(self, db: StateDb, store: ProviderStore):
        self._settings = Settings(db)
        self._store = store

    def tier(self, tier: str) -> TierModel | None:
        check_chat_tier(tier)
        value = self._settings.get(TIERS_GROUP, tier)
        return TierModel(value["provider_id"], value["model"]) if value else None

    def tiers(self) -> dict[str, TierModel]:
        """Every mapped chat tier."""
        return {tier: model for tier in CHAT_TIERS if (model := self.tier(tier)) is not None}

    def set_tier(self, tier: str, provider_id: str, model: str) -> TierModel:
        check_chat_tier(tier)
        if not model or not model.strip():
            raise ValueError("a tier needs a model name")
        self._store.get(provider_id)
        mapped = TierModel(provider_id, model.strip())
        self._settings.set(TIERS_GROUP, tier, {"provider_id": mapped.provider_id, "model": mapped.model})
        return mapped

    def embedding(self) -> tuple[TierModel, int] | None:
        provider_id = self._settings.get(EMBEDDING_GROUP, "provider_id")
        model = self._settings.get(EMBEDDING_GROUP, "model")
        if not provider_id or not model:
            return None
        return TierModel(provider_id, model), self._settings.get(EMBEDDING_GROUP, "dimensions") or DEFAULT_DIMENSIONS

    def set_embedding(self, provider_id: str, model: str, dimensions: int) -> None:
        self._store.get(provider_id)
        self._settings.set(EMBEDDING_GROUP, "provider_id", provider_id)
        self._settings.set(EMBEDDING_GROUP, "model", model)
        self._settings.set(EMBEDDING_GROUP, "dimensions", dimensions)

    def providers_in_use(self) -> set[str]:
        used = {model.provider_id for model in self.tiers().values()}
        embedding = self.embedding()
        if embedding is not None:
            used.add(embedding[0].provider_id)
        return used


def fill_defaults(mapping: TierMapping, provider: Provider, *, dimensions: int = DEFAULT_DIMENSIONS) -> None:
    """Map every unmapped chat tier, and an unset embedding, to the provider's proposed models."""
    current = mapping.tiers()
    for tier, model in defaults.chat_models(provider.kind).items():
        if tier not in current:
            mapping.set_tier(tier, provider.id, model)
    embedding_model = defaults.embedding_model(provider.kind)
    if mapping.embedding() is None and embedding_model:
        mapping.set_embedding(provider.id, embedding_model, dimensions)


class SettingsRoutes:
    """The gateway's ``RouteResolver`` over the app state."""

    def __init__(self, mapping: TierMapping, store: ProviderStore, reader: SecretReader):
        self._mapping = mapping
        self._store = store
        self._reader = reader

    def route(self, tier: str) -> Route:
        if tier == EMBED_TIER:
            embedding = self._mapping.embedding()
            if embedding is None:
                raise RouteError("no embedding model is set; add a provider on the Models page")
            mapped = embedding[0]
        else:
            mapped = self._mapping.tier(tier)
            if mapped is None:
                raise RouteError(f"no model is mapped to the {tier} tier; add a provider on the Models page")
        try:
            return self._store.route(mapped.provider_id, mapped.model, self._reader)
        except SecretError:
            raise RouteError(
                f"the key of provider {mapped.provider_id} cannot be read; enter it again on the Models page"
            ) from None


def bootstrap_from_env(store: ProviderStore, mapping: TierMapping, env: Mapping[str, str]) -> list[Provider]:
    """Create the environment's providers when none exists; returns the providers created."""
    if store.list():
        return []
    created = []
    for kind, setting, field in ENV_PROVIDERS:
        value = env.get(setting, "").strip()
        if value:
            created.append(store.create(kind, **{field: value}))
    if created:
        dimensions = int(env.get("EMBEDDING_DIMENSIONS") or DEFAULT_DIMENSIONS)
        for provider in created:
            fill_defaults(mapping, provider, dimensions=dimensions)
    return created


def bootstrap_providers() -> None:
    """At startup: create the environment's providers in the shared app state; logged, never fatal."""
    try:
        store = ProviderStore(shared_state(), shared_vault())
        created = bootstrap_from_env(store, TierMapping(shared_state(), store), os.environ)
    except Exception:  # noqa: BLE001 - the setup's Models step can still add a provider
        _log.exception("the providers of the environment were not created")
        return
    if created:
        _log.info("created the providers %s from the environment", ", ".join(p.id for p in created))
