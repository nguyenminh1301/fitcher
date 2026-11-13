"""The model clients every caller builds from the shared app state; the SDK is never called."""

from app.llm import clients
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

    fill_defaults(mapping, store.create("openai", api_key=KEY), dimensions=1024)
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


def test_the_embedding_client_uses_the_embedding_setting():
    configure()

    embeddings = clients.embedding_client(1024)

    assert isinstance(embeddings, GatewayEmbeddings) and embeddings.dimensions == 1024
    assert clients.embedding_label() == "openai/text-embedding-3-large"


def test_without_an_embedding_setting_there_is_no_label():
    assert clients.embedding_label() is None


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
