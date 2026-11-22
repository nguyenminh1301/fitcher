"""The model clients every caller builds from the shared app state; the SDK is never called."""

import pytest

from app.llm import clients
from app.llm.embeddings import EmbeddingError
from app.llm.local_embeddings import LocalEmbeddings
from app.llm.gateway import Gateway, GatewayEmbeddings
from app.llm.providers import ProviderStore
from app.llm.routes import TierMapping, TierModel
from app.state.db import shared_state
from app.state.secrets import shared_vault

KEY = "sk-test-clients-key-3131"


def configure():
    store = ProviderStore(shared_state(), shared_vault())
    mapping = TierMapping(shared_state(), store)
    from app.llm.routes import fill_defaults

    fill_defaults(mapping, store.create("openai", api_key=KEY))
    return mapping


def test_the_chat_client_routes_through_the_shared_app_state():
    configure()

    client = clients.chat_client()

    assert isinstance(client, Gateway)
    assert clients.shared_routes().route("fast").model == "openai/gpt-5.4-mini"


def test_an_override_reaches_only_its_own_client():
    configure()

    routes = clients.shared_routes({"fast": TierModel("openai", "gpt-5.5")})

    assert routes.route("fast").model == "openai/gpt-5.5"
    assert clients.shared_routes().route("fast").model == "openai/gpt-5.4-mini"


def test_a_provider_embedding_goes_through_the_gateway():
    configure().set_embedding("openai", "text-embedding-3-large", 1024)

    embeddings = clients.embedding_client(1024)

    assert isinstance(embeddings, GatewayEmbeddings) and embeddings.dimensions == 1024
    assert clients.embedding_label() == "openai/text-embedding-3-large"


def test_a_job_without_the_log_writer_password_logs_no_calls(monkeypatch):
    monkeypatch.delenv("CLICKHOUSE_LOGS_WRITER_PASSWORD", raising=False)

    with clients.job_call_log() as call_log:
        assert call_log is None


def test_bootstrap_copies_the_old_models_page_mapping(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", KEY)
    monkeypatch.setattr(clients, "stored_aliases", lambda: {"sql-gen": "openai-large"})

    clients.bootstrap()

    store = ProviderStore(shared_state(), shared_vault())
    assert TierMapping(shared_state(), store).tier("sql-gen") == TierModel("openai", "gpt-5.5")


def test_the_embedding_runs_locally_by_default_and_shares_one_model():
    first, label = clients.index_embeddings()

    assert isinstance(first, LocalEmbeddings) and first.dimensions == 384
    assert label == "local/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    assert clients.embedding_client(384) is first


def test_a_pack_indexed_at_another_size_asks_for_a_recompile():
    with pytest.raises(EmbeddingError, match="recompile the pack"):
        clients.embedding_client(1024).embed(["a"])


def test_the_compiled_embedding_of_the_active_pack_is_read(monkeypatch, tmp_path):
    (tmp_path / "shop").mkdir()
    (tmp_path / "shop" / "compiled.json").write_text('{"embedding_alias": "openai-embed", "embedding_dimensions": 1024}')
    monkeypatch.setenv("COMPILED_PACK_DIR", str(tmp_path))
    monkeypatch.setenv("ACTIVE_PACK", "shop")

    assert clients.compiled_embedding() == ("openai-embed", 1024)
    monkeypatch.setenv("ACTIVE_PACK", "other")
    assert clients.compiled_embedding() is None
