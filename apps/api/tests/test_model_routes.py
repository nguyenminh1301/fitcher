"""Tier mapping in the app state, the gateway's route resolver and the environment bootstrap."""

from fastapi.testclient import TestClient
import pytest
from state_fixtures import new_state

from app.llm.providers import ProviderNotFound, ProviderStore
from app.llm.routes import (
    bootstrap_from_env, EmbeddingChoice, fill_defaults, LOCAL_DEFAULT, RouteError, SettingsRoutes, TierMapping, TierModel,
)
from app.main import app
from app.state.db import reset_shared_state, shared_state
from app.state.secrets import SecretVault, shared_vault

KEY = "sk-test-route-key-5555"


@pytest.fixture
def state(tmp_path):
    return new_state(tmp_path)


@pytest.fixture
def store(state):
    return ProviderStore(*state)


@pytest.fixture
def mapping(state, store):
    return TierMapping(state[0], store)


def test_a_chat_tier_maps_to_a_model_of_a_configured_provider(store, mapping):
    store.create("openai", api_key=KEY)

    mapping.set_tier("sql-gen", "openai", "gpt-5.4")

    assert mapping.tier("sql-gen") == TierModel(provider_id="openai", model="gpt-5.4")
    assert mapping.tier("fast") is None


def test_a_mapping_needs_a_known_provider_a_model_and_a_chat_tier(store, mapping):
    store.create("openai", api_key=KEY)
    with pytest.raises(ProviderNotFound):
        mapping.set_tier("fast", "anthropic", "claude-haiku-5-5")
    with pytest.raises(ValueError, match="model"):
        mapping.set_tier("fast", "openai", "  ")
    with pytest.raises(ValueError, match="unknown chat tier"):
        mapping.set_tier("embed", "openai", "text-embedding-3-large")


def test_the_first_provider_fills_every_unmapped_chat_tier_and_leaves_the_embedding_local(store, mapping):
    provider = store.create("openai", api_key=KEY)
    other = store.create("anthropic", api_key=KEY)
    mapping.set_tier("sql-gen-hard", other.id, "claude-opus-5-5")

    fill_defaults(mapping, provider, dimensions=1024)

    assert mapping.tiers() == {
        "fast": TierModel("openai", "gpt-5.4-mini"), "sql-small": TierModel("openai", "gpt-5.4-mini"),
        "sql-gen": TierModel("openai", "gpt-5.4"), "sql-gen-hard": TierModel("anthropic", "claude-opus-5-5"),
    }
    assert mapping.embedding() == LOCAL_DEFAULT


def test_the_embedding_runs_locally_until_a_provider_model_is_chosen(store, mapping):
    assert mapping.embedding() == EmbeddingChoice(
        backend="local", model="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", dimensions=384,
    )
    assert mapping.embedding().label == "local/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    fill_defaults(mapping, store.create("anthropic", api_key=KEY), dimensions=1024)
    assert mapping.embedding() == LOCAL_DEFAULT
    assert mapping.tier("fast") == TierModel("anthropic", "claude-haiku-5-5")


def test_the_providers_in_use_are_those_of_a_tier_or_the_embedding(store, mapping):
    fill_defaults(mapping, store.create("openai", api_key=KEY), dimensions=1024)
    store.create("gemini", api_key=KEY)
    assert mapping.providers_in_use() == {"openai"}

    mapping.set_embedding("gemini", "gemini-embedding-001", 768)

    assert mapping.providers_in_use() == {"openai", "gemini"}
    assert mapping.embedding() == EmbeddingChoice("provider", "gemini-embedding-001", 768, provider_id="gemini")


def test_a_local_embedding_model_is_one_of_the_offered_models(store, mapping):
    mapping.set_local_embedding("sentence-transformers/paraphrase-multilingual-mpnet-base-v2")
    assert mapping.embedding().dimensions == 768
    with pytest.raises(ValueError, match="not an offered local embedding model"):
        mapping.set_local_embedding("someone/unknown-model")


def test_the_resolver_routes_a_tier_to_its_provider_with_the_decrypted_key(state, store, mapping):
    fill_defaults(mapping, store.create("openai", api_key=KEY), dimensions=1024)
    mapping.set_embedding("openai", "text-embedding-3-large", 1024)
    routes = SettingsRoutes(mapping, store, state[1].reader())

    fast, embed = routes.route("fast"), routes.route("embed")

    assert (fast.provider, fast.model, fast.api_key) == ("openai", "openai/gpt-5.4-mini", KEY)
    assert embed.model == "openai/text-embedding-3-large"


def test_the_resolver_reads_a_changed_mapping_at_once(state, store, mapping):
    fill_defaults(mapping, store.create("openai", api_key=KEY), dimensions=1024)
    routes = SettingsRoutes(mapping, store, state[1].reader())

    mapping.set_tier("fast", "openai", "gpt-5.5")

    assert routes.route("fast").model == "openai/gpt-5.5"


def test_an_unmapped_tier_raises_route_error(state, store, mapping):
    routes = SettingsRoutes(mapping, store, state[1].reader())

    with pytest.raises(RouteError, match="no model is mapped to the fast tier"):
        routes.route("fast")
    with pytest.raises(RouteError, match="runs locally"):
        routes.route("embed")


def test_the_environment_creates_each_provider_once_and_maps_the_first(store, mapping):
    env = {"OPENAI_API_KEY": KEY, "OLLAMA_URL": "http://host.docker.internal:11434", "EMBEDDING_DIMENSIONS": "1024"}

    created = bootstrap_from_env(store, mapping, env)

    assert [p.id for p in created] == ["openai", "ollama"]
    assert store.get("ollama").base_url == "http://host.docker.internal:11434"
    assert mapping.tier("sql-gen") == TierModel("openai", "gpt-5.4")
    assert mapping.embedding() == LOCAL_DEFAULT
    assert bootstrap_from_env(store, mapping, {**env, "ANTHROPIC_API_KEY": KEY}) == []
    assert [p.id for p in store.list()] == ["openai", "ollama"]


def test_without_provider_settings_the_environment_creates_nothing(store, mapping):
    assert bootstrap_from_env(store, mapping, {"LITELLM_MASTER_KEY": "sk-proxy"}) == []
    assert store.list() == [] and mapping.tiers() == {}


def test_a_key_the_instance_key_cannot_read_raises_route_error(tmp_path, store, mapping):
    fill_defaults(mapping, store.create("openai", api_key=KEY), dimensions=1024)
    db, _ = new_state(tmp_path)  # the same file, opened with the same key...
    other_reader = SecretVault(db, bytes([9]) * 32).reader()  # ...but read with another instance key

    with pytest.raises(RouteError, match="key of provider openai cannot be read"):
        SettingsRoutes(mapping, store, other_reader).route("fast")


def test_starting_the_api_creates_the_environments_provider_once(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", KEY)
    with TestClient(app):
        pass
    with TestClient(app):
        pass

    providers = ProviderStore(shared_state(), shared_vault()).list()
    assert [(p.id, p.key_last4) for p in providers] == [("openai", "5555")]


def test_the_shared_vault_follows_the_shared_state(monkeypatch, tmp_path):
    shared_vault().set("probe", "value-1")
    monkeypatch.setenv("FITCHER_DATA_DIR", str(tmp_path / "other-data"))
    reset_shared_state()

    assert not shared_vault().has("probe")
    assert shared_vault()._db is shared_state()


def test_a_model_with_a_fixed_vector_size_records_that_size(store, mapping):
    # nomic-embed-text always returns 768 floats; OpenAI's model returns the size it is asked for.
    store.create("ollama", base_url="http://host.docker.internal:11434")

    mapping.set_embedding("ollama", "nomic-embed-text", 1024)

    assert mapping.embedding() == EmbeddingChoice("provider", "nomic-embed-text", 768, provider_id="ollama")


def test_the_embedding_route_of_ollama_uses_the_embedding_prefix(state, store, mapping):
    store.create("ollama", base_url="http://host.docker.internal:11434")
    mapping.set_embedding("ollama", "nomic-embed-text", 768)

    assert SettingsRoutes(mapping, store, state[1].reader()).route("embed").model == "ollama/nomic-embed-text"


@pytest.mark.parametrize("dimensions", [0, -5])
def test_an_embedding_needs_a_positive_size(store, mapping, dimensions):
    store.create("openai", api_key=KEY)
    with pytest.raises(ValueError, match="at least one dimension"):
        mapping.set_embedding("openai", "text-embedding-3-large", dimensions)


@pytest.mark.parametrize("env", [
    {"OPENAI_API_KEY": KEY, "EMBEDDING_DIMENSIONS": "invalid"},
    {"OPENAI_API_KEY": KEY, "EMBEDDING_DIMENSIONS": "0"},
    {"OPENAI_API_KEY": KEY, "OLLAMA_URL": "ftp://host.docker.internal:11434"},
])
def test_an_invalid_environment_creates_nothing_so_a_corrected_one_still_bootstraps(store, mapping, env):
    with pytest.raises(ValueError):
        bootstrap_from_env(store, mapping, env)
    assert store.list() == []

    assert [p.id for p in bootstrap_from_env(store, mapping, {"OPENAI_API_KEY": KEY})] == ["openai"]
    assert mapping.tier("fast") == TierModel("openai", "gpt-5.4-mini")


def test_an_override_replaces_a_tiers_model_for_one_resolver_only(state, store, mapping):
    fill_defaults(mapping, store.create("openai", api_key=KEY), dimensions=1024)

    trial = SettingsRoutes(mapping, store, state[1].reader(), overrides={"sql-gen": TierModel("openai", "gpt-5.5")})

    assert trial.route("sql-gen").model == "openai/gpt-5.5"
    assert SettingsRoutes(mapping, store, state[1].reader()).route("sql-gen").model == "openai/gpt-5.4"


def test_the_resolver_names_each_tiers_provider_and_model(state, store, mapping):
    fill_defaults(mapping, store.create("openai", api_key=KEY), dimensions=1024)

    labels = SettingsRoutes(mapping, store, state[1].reader(), overrides={"fast": TierModel("openai", "gpt-5.5")}).labels()

    assert labels == {"fast": "openai/gpt-5.5", "sql-small": "openai/gpt-5.4-mini", "sql-gen": "openai/gpt-5.4",
                      "sql-gen-hard": "openai/gpt-5.5",
                      "embed": "local/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"}


def test_the_aliases_mapped_before_the_app_state_are_copied_once(store, mapping):
    env = {"OPENAI_API_KEY": KEY, "ANTHROPIC_API_KEY": KEY, "MODEL_TIER_FAST": "anthropic-small",
           "MODEL_TIER_SQL_GEN": "openai-large"}
    # The admin's change on the old Models page wins over the environment default.
    stored = {"sql-gen": "anthropic-medium", "sql-small": "an-alias-nobody-knows"}

    bootstrap_from_env(store, mapping, env, legacy_aliases=lambda: stored)

    assert mapping.tier("fast") == TierModel("anthropic", "claude-haiku-5-5")
    assert mapping.tier("sql-gen") == TierModel("anthropic", "claude-sonnet-5-5")
    assert mapping.tier("sql-small") == TierModel("openai", "gpt-5.4-mini")


def test_an_alias_of_a_provider_the_environment_does_not_set_keeps_the_default(store, mapping):
    bootstrap_from_env(store, mapping, {"OPENAI_API_KEY": KEY, "MODEL_TIER_FAST": "gemini-small"})

    assert mapping.tier("fast") == TierModel("openai", "gpt-5.4-mini")



def test_a_pack_compiled_with_a_provider_embedding_keeps_it(store, mapping):
    # Vectors indexed before the app state existed were made by the proxy's openai-embed alias at 1024 floats.
    bootstrap_from_env(store, mapping, {"OPENAI_API_KEY": KEY}, compiled_embedding=lambda: ("openai-embed", 1024))

    assert mapping.embedding() == EmbeddingChoice("provider", "text-embedding-3-large", 1024, provider_id="openai")


@pytest.mark.parametrize("compiled", [None, ("local/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", 384),
                                      ("anthropic-embed", 1024)])
def test_otherwise_the_embedding_stays_local(store, mapping, compiled):
    bootstrap_from_env(store, mapping, {"OPENAI_API_KEY": KEY}, compiled_embedding=lambda: compiled)

    assert mapping.embedding() == LOCAL_DEFAULT
