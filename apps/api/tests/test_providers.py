"""The provider store over the app state: kinds, validation, keys kept in the vault, routes."""

import sqlite3

import pytest
from state_fixtures import new_state

from app.llm import defaults
from app.llm.providers import KINDS, ProviderError, ProviderNotFound, ProviderStore

KEY = "sk-test-provider-key-9876"


@pytest.fixture
def state(tmp_path):
    return new_state(tmp_path)


@pytest.fixture
def store(state):
    return ProviderStore(*state)


def test_a_hosted_provider_keeps_its_key_in_the_vault_and_shows_only_the_last_four(state, store):
    db, vault = state

    provider = store.create("openai", api_key=KEY)

    assert (provider.id, provider.name, provider.kind) == ("openai", "OpenAI", "openai")
    assert provider.key_set and provider.key_last4 == "9876"
    assert vault.reader().get("provider:openai:api_key") == KEY
    dump = "\n".join(db.connection().iterdump())
    assert KEY not in dump
    assert KEY not in repr(provider)


def test_a_second_provider_of_a_kind_gets_its_own_id(store):
    store.create("openai", api_key=KEY)

    second = store.create("openai", name="OpenAI (team)", api_key="sk-other-0001")

    assert second.id == "openai-2"
    assert [p.id for p in store.list()] == ["openai", "openai-2"]


def test_names_are_unique(store):
    store.create("ollama", base_url="http://host.docker.internal:11434")
    with pytest.raises(ProviderError, match="name"):
        store.create("ollama", base_url="http://other:11434")


@pytest.mark.parametrize("kind", ["openai", "anthropic", "gemini"])
def test_a_hosted_provider_needs_a_key_and_takes_no_base_url(store, kind):
    with pytest.raises(ProviderError, match="needs an API key"):
        store.create(kind)
    with pytest.raises(ProviderError, match="base URL"):
        store.create(kind, api_key=KEY, base_url="http://example:1/v1")


@pytest.mark.parametrize("kind", ["ollama", "openai_compatible"])
def test_a_model_server_needs_an_http_base_url(store, kind):
    with pytest.raises(ProviderError, match="needs a base URL"):
        store.create(kind)
    with pytest.raises(ProviderError, match="http"):
        store.create(kind, base_url="file:///etc/passwd")


def test_an_openai_compatible_endpoint_takes_an_optional_key(store):
    keyless = store.create("openai_compatible", name="LM Studio", base_url="http://host.docker.internal:1234/v1/")
    keyed = store.create("openai_compatible", name="OpenRouter", base_url="https://openrouter.ai/api/v1", api_key=KEY)

    assert keyless.base_url == "http://host.docker.internal:1234/v1"
    assert not keyless.key_set and keyless.key_last4 is None
    assert keyed.key_set


def test_an_unknown_kind_is_refused(store):
    with pytest.raises(ProviderError, match="kind"):
        store.create("azure", api_key=KEY)
    assert set(KINDS) == {"openai", "anthropic", "gemini", "ollama", "openai_compatible"}


def test_the_state_refuses_an_unknown_kind_as_well(state):
    db, _ = state
    with pytest.raises(sqlite3.IntegrityError), db.write() as conn:
        conn.execute("INSERT INTO providers (id, name, kind, base_url, created_at) VALUES ('x', 'x', 'azure', NULL, '')")


def test_update_replaces_the_key_and_renames_without_touching_the_rest(state, store):
    store.create("anthropic", api_key=KEY)

    updated = store.update("anthropic", name="Claude", api_key="sk-ant-new-4321")

    assert (updated.name, updated.key_last4, updated.kind) == ("Claude", "4321", "anthropic")
    assert state[1].reader().get("provider:anthropic:api_key") == "sk-ant-new-4321"
    assert store.update("anthropic").key_last4 == "4321"


def test_update_checks_the_base_url_like_create(store):
    store.create("ollama", base_url="http://host.docker.internal:11434")
    with pytest.raises(ProviderError, match="http"):
        store.update("ollama", base_url="ftp://x")


def test_delete_removes_the_row_and_its_key(state, store):
    store.create("gemini", api_key=KEY)

    store.delete("gemini")

    assert store.list() == []
    assert not state[1].has("provider:gemini:api_key")
    with pytest.raises(ProviderNotFound):
        store.get("gemini")
    with pytest.raises(ProviderNotFound):
        store.delete("gemini")


@pytest.mark.parametrize(("kind", "options", "model", "expected"), [
    ("openai", {"api_key": KEY}, "gpt-5.4-mini", ("openai/gpt-5.4-mini", KEY, None)),
    ("anthropic", {"api_key": KEY}, "claude-haiku-5-5", ("anthropic/claude-haiku-5-5", KEY, None)),
    ("gemini", {"api_key": KEY}, "gemini-2.5-flash", ("gemini/gemini-2.5-flash", KEY, None)),
    ("ollama", {"base_url": "http://host.docker.internal:11434"}, "qwen2.5-coder:7b",
     ("ollama_chat/qwen2.5-coder:7b", None, "http://host.docker.internal:11434")),
    ("openai_compatible", {"base_url": "http://lab:1234/v1"}, "local-model",
     ("openai/local-model", None, "http://lab:1234/v1")),
])
def test_a_route_names_the_sdk_model_and_carries_the_decrypted_key(state, store, kind, options, model, expected):
    provider = store.create(kind, **options)

    route = store.route(provider.id, model, state[1].reader())

    assert (route.model, route.api_key, route.api_base) == expected
    assert route.provider == provider.id


def test_every_kind_has_a_proposed_model_for_each_chat_tier_or_none():
    for kind in KINDS:
        proposal = defaults.chat_models(kind)
        assert set(proposal) <= {"fast", "sql-small", "sql-gen", "sql-gen-hard"}
    assert defaults.chat_models("openai") == {
        "fast": "gpt-5.4-mini", "sql-small": "gpt-5.4-mini", "sql-gen": "gpt-5.4", "sql-gen-hard": "gpt-5.5",
    }
    assert defaults.chat_models("openai_compatible") == {}
    assert defaults.embedding_model("openai") == "text-embedding-3-large"
    assert defaults.embedding_model("anthropic") is None
