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

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import logging
import os

from app.llm import defaults
from app.llm.gateway import Route
from app.llm.providers import check_fields, Provider, ProviderStore
from app.llm.tiers import check_chat_tier, CHAT_TIERS, EMBED_TIER, setting_name
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


# The catalog aliases of the LiteLLM Proxy era and the model each one named, so a mapping made
# before the app state (MODEL_TIER_<TIER> or the old Models page) is copied once by bootstrap.
LEGACY_ALIASES = {
    "openai-small": ("openai", "gpt-5.4-mini"), "openai-medium": ("openai", "gpt-5.4"),
    "openai-large": ("openai", "gpt-5.5"), "anthropic-small": ("anthropic", "claude-haiku-5-5"),
    "anthropic-medium": ("anthropic", "claude-sonnet-5-5"), "gemini-small": ("gemini", "gemini-2.5-flash"),
    "gemini-medium": ("gemini", "gemini-2.5-pro"), "local-small": ("ollama", "qwen2.5-coder:7b"),
}


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
        if dimensions < 1:
            raise ValueError("the embedding needs at least one dimension")
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
        mapping.set_embedding(provider.id, embedding_model, defaults.fixed_dimensions(embedding_model) or dimensions)


class SettingsRoutes:
    """The gateway's ``RouteResolver`` over the app state."""

    def __init__(self, mapping: TierMapping, store: ProviderStore, reader: SecretReader,
                 overrides: Mapping[str, TierModel] | None = None):
        """``overrides`` maps chat tiers to other models for this resolver only, as an eval run of one model does."""
        self._mapping = mapping
        self._store = store
        self._reader = reader
        self._overrides = dict(overrides or {})

    def _chat(self, tier: str) -> TierModel | None:
        return self._overrides.get(tier) or self._mapping.tier(tier)

    def labels(self) -> dict[str, str]:
        """``provider/model`` of every mapped tier, as eval reports record them."""
        labels = {tier: f"{model.provider_id}/{model.model}" for tier in CHAT_TIERS if (model := self._chat(tier))}
        embedding = self._mapping.embedding()
        if embedding is not None:
            labels[EMBED_TIER] = f"{embedding[0].provider_id}/{embedding[0].model}"
        return labels

    def route(self, tier: str) -> Route:
        if tier == EMBED_TIER:
            embedding = self._mapping.embedding()
            if embedding is None:
                raise RouteError("no embedding model is set; add a provider on the Models page")
            mapped, embedding_call = embedding[0], True
        else:
            embedding_call = False
            mapped = self._chat(tier)
            if mapped is None:
                raise RouteError(f"no model is mapped to the {tier} tier; add a provider on the Models page")
        try:
            return self._store.route(mapped.provider_id, mapped.model, self._reader, embedding=embedding_call)
        except SecretError:
            raise RouteError(
                f"the key of provider {mapped.provider_id} cannot be read; enter it again on the Models page"
            ) from None


def _dimensions(env: Mapping[str, str]) -> int:
    value = env.get("EMBEDDING_DIMENSIONS") or str(DEFAULT_DIMENSIONS)
    try:
        dimensions = int(value)
    except ValueError:
        raise ValueError(f"EMBEDDING_DIMENSIONS must be a whole number, got {value[:20]!r}") from None
    if dimensions < 1:
        raise ValueError("EMBEDDING_DIMENSIONS must be at least 1")
    return dimensions


def _copy_legacy(mapping: TierMapping, created: list[Provider], aliases: Mapping[str, str]) -> None:
    by_kind = {provider.kind: provider.id for provider in created}
    for tier, alias in aliases.items():
        kind, model = LEGACY_ALIASES.get(alias, (None, None))
        if tier in CHAT_TIERS and kind in by_kind:
            mapping.set_tier(tier, by_kind[kind], model)


def bootstrap_from_env(
    store: ProviderStore, mapping: TierMapping, env: Mapping[str, str],
    legacy_aliases: Callable[[], Mapping[str, str]] | None = None,
) -> list[Provider]:
    """Create the environment's providers when none exists; returns the providers created.

    Every setting is checked before the first write, so an invalid environment creates nothing and a
    corrected one bootstraps on the next start. A tier mapped before the app state existed keeps its
    model: the ``MODEL_TIER_<TIER>`` aliases, then the old Models page's ``legacy_aliases``, are
    copied when their provider was created.
    """
    if store.list():
        return []
    wanted = [(kind, {field: env[setting].strip()}) for kind, setting, field in ENV_PROVIDERS
              if env.get(setting, "").strip()]
    if not wanted:
        return []
    dimensions = _dimensions(env)
    for kind, fields in wanted:
        check_fields(kind, **fields)
    created = [store.create(kind, **fields) for kind, fields in wanted]
    aliases = {tier: env[setting_name(tier)] for tier in CHAT_TIERS if env.get(setting_name(tier))}
    if legacy_aliases is not None:
        aliases.update(legacy_aliases())
    _copy_legacy(mapping, created, aliases)
    for provider in created:
        fill_defaults(mapping, provider, dimensions=dimensions)
    return created


def bootstrap_providers(legacy_aliases: Callable[[], Mapping[str, str]] | None = None) -> None:
    """At startup: create the environment's providers in the shared app state; logged, never fatal."""
    try:
        store = ProviderStore(shared_state(), shared_vault())
        created = bootstrap_from_env(store, TierMapping(shared_state(), store), os.environ, legacy_aliases)
    except Exception:  # noqa: BLE001 - the setup's Models step can still add a provider
        _log.exception("the providers of the environment were not created")
        return
    if created:
        _log.info("created the providers %s from the environment", ", ".join(p.id for p in created))
