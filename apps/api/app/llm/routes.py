"""Which model of which provider serves each tier, and the gateway's resolver over it (DECISIONS §2).

The mapping lives in the app state: ``tier_chain`` holds each chat tier's
ordered fallback chain of models (the first answers unless it fails), and
setting group ``llm.embedding`` the embed tier's backend, model and vector
size. Any model of a configured provider may serve a chat tier; an eval result
informs the choice and does not gate it. ``model_mode`` says whether the owner
sets the chains (``manual``) or they are chosen from the model catalog
(``auto_free``, ``auto_best``; ``app/llm/auto.py``).
Adding the first provider fills every unmapped chat tier from ``defaults``,
and, while no embedding was chosen, the embed tier with the provider's
embedding model: the local models lost retrieval recall against it
(DECISIONS §14). With no provider that offers one, or when an admin chooses
it, the embedding runs locally (``app/llm/local_embeddings.py``) and indexing
a pack needs no key.

``SettingsRoutes`` reads the mapping on every call, so a change applies to the
next call in every process that shares the app state.

When no provider exists yet, ``bootstrap_from_env`` creates one per provider
setting of the environment (``OPENAI_API_KEY``, ``ANTHROPIC_API_KEY``,
``GEMINI_API_KEY``, ``OLLAMA_URL``) and maps the tiers to the first, so a
scripted start or CI needs no setup step. When the active pack was compiled
with a provider's embedding model before the app state existed, that model and
vector size are kept, so the pack's vectors still match until an admin changes
the embedding and recompiles.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import logging
import os

from app.llm import defaults
from app.llm.gateway import Route
from app.llm.local_embeddings import LOCAL_MODELS
from app.llm.providers import check_fields, Provider, ProviderStore
from app.llm.tiers import check_chat_tier, CHAT_TIERS, EMBED_TIER, setting_name
from app.state.db import shared_state, StateDb
from app.state.secrets import SecretError, SecretReader, shared_vault
from app.state.settings import Settings

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


# The embedding model of the proxy era's openai-embed alias.
LEGACY_EMBEDDING_ALIASES = {"openai-embed": ("openai", "text-embedding-3-large")}


MODES = ("auto_free", "auto_best", "manual")
# The most models a chain tries; more would only delay the error of a request every model refuses.
MAX_CHAIN = 6


class RouteError(LookupError):
    """No model is mapped to the tier."""


@dataclass(frozen=True)
class TierModel:
    provider_id: str
    model: str


@dataclass(frozen=True)
class EmbeddingChoice:
    """The embed tier: a local model, or a provider's model, and the vector size it returns."""

    backend: str
    model: str
    dimensions: int
    provider_id: str | None = None

    @property
    def label(self) -> str:
        """``local/<model>`` or ``<provider>/<model>``, as ``compiled.json`` and eval reports record it."""
        return f"{self.provider_id if self.backend == 'provider' else 'local'}/{self.model}"


LOCAL_DEFAULT = EmbeddingChoice("local", defaults.LOCAL_EMBEDDING_MODEL, LOCAL_MODELS[defaults.LOCAL_EMBEDDING_MODEL])


class TierMapping:
    def __init__(self, db: StateDb, store: ProviderStore):
        self._db = db
        self._settings = Settings(db)
        self._store = store

    def chain(self, tier: str) -> list[TierModel]:
        """The tier's models in the order they are tried."""
        check_chat_tier(tier)
        rows = self._db.connection().execute(
            "SELECT provider_id, model FROM tier_chain WHERE tier = ? ORDER BY position", (tier,),
        ).fetchall()
        return [TierModel(provider_id, model) for provider_id, model in rows]

    def tier(self, tier: str) -> TierModel | None:
        """The tier's first model."""
        chain = self.chain(tier)
        return chain[0] if chain else None

    def tiers(self) -> dict[str, TierModel]:
        """The first model of every mapped chat tier."""
        return {tier: model for tier in CHAT_TIERS if (model := self.tier(tier)) is not None}

    def set_chain(self, tier: str, links: list[TierModel]) -> list[TierModel]:
        """Replace the tier's chain; a model listed twice is kept at its first place."""
        check_chat_tier(tier)
        chain: list[TierModel] = []
        for link in links:
            if not link.model or not link.model.strip():
                raise ValueError("a tier needs a model name")
            self._store.get(link.provider_id)
            mapped = TierModel(link.provider_id, link.model.strip())
            if mapped not in chain:
                chain.append(mapped)
        if not chain:
            raise ValueError("a tier needs at least one model")
        if len(chain) > MAX_CHAIN:
            raise ValueError(f"a tier tries at most {MAX_CHAIN} models")
        with self._db.write() as conn:
            conn.execute("DELETE FROM tier_chain WHERE tier = ?", (tier,))
            conn.executemany(
                "INSERT INTO tier_chain (tier, position, provider_id, model) VALUES (?, ?, ?, ?)",
                [(tier, position, link.provider_id, link.model) for position, link in enumerate(chain)],
            )
        return chain

    def set_tier(self, tier: str, provider_id: str, model: str) -> TierModel:
        """Make one model the tier's whole chain."""
        return self.set_chain(tier, [TierModel(provider_id, model)])[0]

    def mode(self) -> tuple[str, datetime | None]:
        """How the chains are chosen, and when an automatic mode last chose them."""
        row = self._db.connection().execute("SELECT mode, refreshed_at FROM model_mode WHERE id = 1").fetchone()
        if row is None:
            return "manual", None
        return row[0], datetime.fromisoformat(row[1]) if row[1] else None

    def set_mode(self, mode: str, refreshed_at: datetime | None = None) -> None:
        if mode not in MODES:
            raise ValueError(f"unknown model mode {mode!r}; use one of {', '.join(MODES)}")
        with self._db.write() as conn:
            conn.execute(
                "INSERT INTO model_mode (id, mode, refreshed_at) VALUES (1, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET mode = excluded.mode, refreshed_at = excluded.refreshed_at",
                (mode, refreshed_at.astimezone(UTC).isoformat() if refreshed_at else None),
            )

    def embedding_chosen(self) -> bool:
        """Whether a provider or an admin set the embedding; until then it is the local default."""
        return self._settings.get(EMBEDDING_GROUP, "backend") is not None

    def embedding(self) -> EmbeddingChoice:
        if self._settings.get(EMBEDDING_GROUP, "backend") != "provider":
            model = self._settings.get(EMBEDDING_GROUP, "model")
            return EmbeddingChoice("local", model, LOCAL_MODELS[model]) if model in LOCAL_MODELS else LOCAL_DEFAULT
        return EmbeddingChoice("provider", self._settings.get(EMBEDDING_GROUP, "model"),
                               self._settings.get(EMBEDDING_GROUP, "dimensions") or DEFAULT_DIMENSIONS,
                               provider_id=self._settings.get(EMBEDDING_GROUP, "provider_id"))

    def set_embedding(self, provider_id: str, model: str, dimensions: int) -> EmbeddingChoice:
        """Embed with a provider's model; a model that returns only one size records that size."""
        dimensions = defaults.fixed_dimensions(model) or dimensions
        if dimensions < 1:
            raise ValueError("the embedding needs at least one dimension")
        if not model or not model.strip():
            raise ValueError("an embedding needs a model name")
        self._store.get(provider_id)
        self._settings.set(EMBEDDING_GROUP, "provider_id", provider_id)
        self._settings.set(EMBEDDING_GROUP, "model", model.strip())
        self._settings.set(EMBEDDING_GROUP, "dimensions", dimensions)
        self._settings.set(EMBEDDING_GROUP, "backend", "provider")
        return self.embedding()

    def set_local_embedding(self, model: str) -> EmbeddingChoice:
        if model not in LOCAL_MODELS:
            raise ValueError(f"{model!r} is not an offered local embedding model; use one of {', '.join(LOCAL_MODELS)}")
        self._settings.set(EMBEDDING_GROUP, "model", model)
        self._settings.set(EMBEDDING_GROUP, "dimensions", LOCAL_MODELS[model])
        self._settings.set(EMBEDDING_GROUP, "backend", "local")
        return self.embedding()

    def drop_provider(self, provider_id: str) -> list[str]:
        """Take the provider out of every chain; returns the chat tiers left with no model.

        An embedding the provider served goes back to the local default model, so questions keep their search.
        """
        emptied = []
        with self._db.write() as conn:
            for tier in CHAT_TIERS:
                rows = conn.execute(
                    "SELECT provider_id, model FROM tier_chain WHERE tier = ? ORDER BY position", (tier,),
                ).fetchall()
                kept = [row for row in rows if row[0] != provider_id]
                if len(kept) == len(rows):
                    continue
                conn.execute("DELETE FROM tier_chain WHERE tier = ?", (tier,))
                conn.executemany(
                    "INSERT INTO tier_chain (tier, position, provider_id, model) VALUES (?, ?, ?, ?)",
                    [(tier, position, kept_provider, model) for position, (kept_provider, model) in enumerate(kept)],
                )
                if not kept:
                    emptied.append(tier)
        if self.embedding().provider_id == provider_id:
            self.set_local_embedding(LOCAL_DEFAULT.model)
        return emptied

    def providers_needed(self) -> set[str]:
        """The providers that alone serve a chat tier, or serve the embedding: removing one would leave it unserved."""
        needed = set()
        for tier in CHAT_TIERS:
            providers = {link.provider_id for link in self.chain(tier)}
            if len(providers) == 1:
                needed |= providers
        embedding = self.embedding()
        if embedding.provider_id:
            needed.add(embedding.provider_id)
        return needed

    def providers_in_use(self) -> set[str]:
        used = {link.provider_id for tier in CHAT_TIERS for link in self.chain(tier)}
        embedding = self.embedding()
        if embedding.provider_id:
            used.add(embedding.provider_id)
        return used


def fill_defaults(mapping: TierMapping, provider: Provider, installed: list[str] | None = None) -> None:
    """Map every unmapped chat tier to the provider's proposed models, and an embedding nobody chose to an Ollama one.

    ``installed`` is what an Ollama server listed: its models are proposed only from those, because a model
    the server does not have fails every question. A hosted provider's embedding model is never proposed: the
    local model indexes a pack without a quota, while a free key's limit (Gemini embeds 100 texts a minute) cannot
    index a pack with thousands of column values; an admin can still choose a provider's model.
    """
    current = mapping.tiers()
    proposed = defaults.chat_models(provider.kind)
    embedding_model = defaults.embedding_model(provider.kind) if provider.kind == "ollama" else None
    if provider.kind == "ollama" and installed is not None:
        chat = defaults.installed_chat_model(installed)
        proposed = dict.fromkeys(proposed, chat) if chat else {}
        embedding_model = defaults.installed_embedding_model(installed)
    for tier, model in proposed.items():
        if tier not in current:
            mapping.set_tier(tier, provider.id, model)
    if embedding_model and not mapping.embedding_chosen():
        mapping.set_embedding(provider.id, embedding_model, defaults.proposed_dimensions(embedding_model) or DEFAULT_DIMENSIONS)


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

    def chain(self, tier: str) -> list[list[Route]]:
        """The tier's chain for the gateway: per model, one route per key of its provider.

        An eval run's override is the whole chain, so the run measures that model alone. A link whose key
        cannot be read is skipped while another link remains.
        """
        if tier == EMBED_TIER:
            return [[self.route(tier)]]
        links = [self._overrides[tier]] if tier in self._overrides else self._mapping.chain(tier)
        if not links:
            raise RouteError(f"no model is mapped to the {tier} tier; add a provider on the Models page")
        chain, unreadable = [], None
        for link in links:
            try:
                chain.append(self._store.routes(link.provider_id, link.model, self._reader))
            except SecretError:
                unreadable = link.provider_id
        if not chain:
            raise RouteError(f"the key of provider {unreadable} cannot be read; enter it again on the Models page")
        return chain

    def labels(self) -> dict[str, str]:
        """``provider/model`` of every mapped tier, as eval reports record them."""
        labels = {tier: f"{model.provider_id}/{model.model}" for tier in CHAT_TIERS if (model := self._chat(tier))}
        labels[EMBED_TIER] = self._mapping.embedding().label
        return labels

    def route(self, tier: str) -> Route:
        if tier == EMBED_TIER:
            embedding = self._mapping.embedding()
            if embedding.backend != "provider":
                raise RouteError("the embedding runs locally; no provider serves it")
            mapped, embedding_call = TierModel(embedding.provider_id, embedding.model), True
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


def _copy_legacy(mapping: TierMapping, created: list[Provider], aliases: Mapping[str, str]) -> None:
    by_kind = {provider.kind: provider.id for provider in created}
    for tier, alias in aliases.items():
        kind, model = LEGACY_ALIASES.get(alias, (None, None))
        if tier in CHAT_TIERS and kind in by_kind:
            mapping.set_tier(tier, by_kind[kind], model)


def _keep_compiled_embedding(mapping: TierMapping, created: list[Provider], compiled: tuple[str, int] | None) -> None:
    """Keep the embedding model a pack was compiled with, so its vectors still match."""
    if compiled is None:
        return
    label, dimensions = compiled
    if label.startswith("local/") and label.removeprefix("local/") in LOCAL_MODELS:
        mapping.set_local_embedding(label.removeprefix("local/"))
        return
    kind, model = LEGACY_EMBEDDING_ALIASES.get(label, (None, None))
    if kind is None and "/" in label and not label.startswith("local/"):
        kind, model = label.split("/", 1)
    by_kind = {provider.kind: provider.id for provider in created}
    by_id = {provider.id for provider in created}
    provider_id = by_kind.get(kind) or (kind if kind in by_id else None)
    if provider_id and model:
        mapping.set_embedding(provider_id, model, dimensions)


def bootstrap_from_env(
    store: ProviderStore, mapping: TierMapping, env: Mapping[str, str],
    legacy_aliases: Callable[[], Mapping[str, str]] | None = None,
    compiled_embedding: Callable[[], tuple[str, int] | None] | None = None,
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
    for kind, fields in wanted:
        check_fields(kind, **fields)
    created = [store.create(kind, **fields) for kind, fields in wanted]
    aliases = {tier: env[setting_name(tier)] for tier in CHAT_TIERS if env.get(setting_name(tier))}
    if legacy_aliases is not None:
        aliases.update(legacy_aliases())
    _copy_legacy(mapping, created, aliases)
    for provider in created:
        fill_defaults(mapping, provider)
    if compiled_embedding is not None:
        _keep_compiled_embedding(mapping, created, compiled_embedding())
    return created


def bootstrap_providers(
    legacy_aliases: Callable[[], Mapping[str, str]] | None = None,
    compiled_embedding: Callable[[], tuple[str, int] | None] | None = None,
) -> None:
    """At startup: create the environment's providers in the shared app state; logged, never fatal."""
    try:
        store = ProviderStore(shared_state(), shared_vault())
        created = bootstrap_from_env(store, TierMapping(shared_state(), store), os.environ, legacy_aliases,
                                     compiled_embedding)
    except Exception:  # noqa: BLE001 - the setup's Models step can still add a provider
        _log.exception("the providers of the environment were not created")
        return
    if created:
        _log.info("created the providers %s from the environment", ", ".join(p.id for p in created))
