"""The provider and tier endpoints over a temporary app state; listing and the test call are fakes."""

from fastapi.testclient import TestClient
import logging
import pytest

from state_fixtures import new_state

from app.api import providers as providers_api, runtime, setup as setup_api
from app.llm.client import LLMError
from app.llm.provider_models import ModelListError
from app.main import app

ADMIN = {}
VIEWER = {}
KEY = "sk-test-endpoint-key-7777"


class Actions:
    def __init__(self):
        self.records = []

    def record_action(self, record) -> None:
        self.records.append(record)


class Fakes:
    def __init__(self):
        self.models = ["gpt-5.4", "gpt-5.4-mini"]
        self.listed_with: list[str | None] = []
        self.checked_with: list[str | None] = []
        self.refused_key: str | None = None
        self.list_error: ModelListError | None = None
        self.probed: list = []
        self.probe_error: LLMError | None = None
        self.compiled: tuple[str, int] | None = ("local/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", 384)

    def lister(self, provider, api_key):
        self.listed_with.append(api_key)
        if self.list_error:
            raise self.list_error
        return self.models

    def checker(self, provider, api_key):
        """Lists the models once the key is accepted, as ``checked_models`` does."""
        self.checked_with.append(api_key)
        if api_key is not None and api_key == self.refused_key:
            raise ModelListError(f"{provider.name} refused the key (HTTP 401)")
        if self.list_error:
            raise self.list_error
        return self.models

    def probe(self, route) -> None:
        self.probed.append(route)
        if self.probe_error:
            raise self.probe_error


@pytest.fixture
def fakes():
    return Fakes()


@pytest.fixture
def actions():
    return Actions()


@pytest.fixture
def client(tmp_path, fakes, actions):
    db, vault = new_state(tmp_path)
    app.dependency_overrides[setup_api.get_state_db] = lambda: db
    app.dependency_overrides[providers_api.get_vault] = lambda: vault
    app.dependency_overrides[providers_api.get_model_lister] = lambda: fakes.lister
    app.dependency_overrides[providers_api.get_key_checker] = lambda: fakes.checker
    app.dependency_overrides[providers_api.get_probe] = lambda: fakes.probe
    app.dependency_overrides[runtime.get_admin_action_log] = lambda: actions
    app.dependency_overrides[providers_api.get_compiled_embedding] = lambda: fakes.compiled
    app.dependency_overrides[providers_api.get_catalog] = lambda: catalog_with({})
    app.dependency_overrides[providers_api.get_latency] = lambda: dict
    yield TestClient(app)
    app.dependency_overrides.clear()


def add_openai(client):
    response = client.post("/providers", headers=ADMIN, json={"kind": "openai", "api_key": KEY})
    assert response.status_code == 201, response.text
    return response


def test_adding_the_first_provider_shows_only_the_key_ending_and_fills_the_tiers(client, actions):
    body = add_openai(client).json()

    keys = body.pop("keys")
    assert body == {"id": "openai", "name": "OpenAI", "kind": "openai", "base_url": None, "key_set": True,
                    "key_last4": "7777", "hosted": True, "in_use": True}
    assert [(key["label"], key["last4"]) for key in keys] == [("", "7777")]
    tiers = client.get("/models/tiers", headers=ADMIN).json()
    fast = tiers["tiers"][0]
    assert (fast["tier"], fast["provider_id"], fast["model"], fast["eval"]["evaluated"]) == ("fast", "openai", "gpt-5.4-mini", False)
    # The embedding stays on the local model the pack was indexed with, so nothing needs a recompile.
    assert tiers["embedding"] == {"backend": "local", "provider_id": None,
                                  "model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
                                  "dimensions": 384, "needs_reindex": False}
    [action] = actions.records
    assert (action.action, action.target) == ("provider_add", "openai")
    assert KEY not in action.new_value and "7777" in action.new_value


def test_an_invalid_provider_is_refused_with_the_reason(client):
    response = client.post("/providers", headers=ADMIN, json={"kind": "ollama"})
    assert response.status_code == 422
    assert "needs a base URL" in response.json()["detail"]


def test_no_response_ever_contains_the_key(client):
    responses = [
        add_openai(client),
        client.get("/providers", headers=ADMIN),
        client.patch("/providers/openai", headers=ADMIN, json={"api_key": KEY + "-new"}),
        client.get("/models/tiers", headers=ADMIN),
        client.post("/providers/openai/test", headers=ADMIN, json={}),
    ]
    assert all(KEY not in response.text for response in responses)


def test_a_provider_is_renamed_and_its_key_replaced(client):
    add_openai(client)

    body = client.patch("/providers/openai", headers=ADMIN, json={"name": "OpenAI team", "api_key": "sk-new-1212"}).json()

    assert (body["name"], body["key_last4"]) == ("OpenAI team", "1212")
    assert client.patch("/providers/nope", headers=ADMIN, json={"name": "x"}).status_code == 404


def test_moving_a_keyed_provider_to_a_new_address_without_its_key_is_refused(client):
    client.post("/providers", headers=ADMIN, json={"kind": "openai_compatible", "name": "Lab",
                                                   "base_url": "https://models.example/v1", "api_key": KEY})

    refused = client.patch("/providers/openai-compatible", headers=ADMIN, json={"base_url": "http://attacker.example/v1"})

    assert refused.status_code == 422 and "key" in refused.json()["detail"]
    assert client.get("/providers", headers=ADMIN).json()[0]["base_url"] == "https://models.example/v1"


def test_a_provider_in_use_is_removed_and_its_tiers_move_to_a_remaining_provider(client, fakes):
    add_openai(client)
    fakes.models = ["gemini-2.5-flash", "gemini-2.5-pro"]
    assert client.post("/providers", headers=ADMIN, json={"kind": "gemini", "api_key": KEY}).json()["in_use"] is False

    assert client.delete("/providers/openai", headers=ADMIN).status_code == 204

    body = client.get("/models/tiers", headers=ADMIN).json()
    assert {(tier["tier"], tier["provider_id"], tier["model"]) for tier in body["tiers"]} == {
        ("fast", "gemini", "gemini-2.5-flash"), ("sql-small", "gemini", "gemini-2.5-flash"),
        ("sql-gen", "gemini", "gemini-2.5-pro"), ("sql-gen-hard", "gemini", "gemini-2.5-pro"),
    }
    assert body["embedding"]["backend"] == "local"
    assert [provider["id"] for provider in client.get("/providers", headers=ADMIN).json()] == ["gemini"]


def test_the_last_provider_can_be_removed_and_leaves_its_tiers_unmapped(client):
    add_openai(client)

    assert client.delete("/providers/openai", headers=ADMIN).status_code == 204

    assert all(
        tier["provider_id"] is None and tier["chain"] == [] for tier in client.get("/models/tiers", headers=ADMIN).json()["tiers"])


def test_a_key_the_provider_refuses_is_not_stored(client, fakes, actions):
    fakes.refused_key = KEY

    refused = client.post("/providers", headers=ADMIN, json={"kind": "openai", "api_key": KEY})

    assert refused.status_code == 422 and "refused the key" in refused.json()["detail"]
    assert client.get("/providers", headers=ADMIN).json() == []
    assert all(
        tier["provider_id"] is None and tier["chain"] == [] for tier in client.get("/models/tiers", headers=ADMIN).json()["tiers"])
    assert actions.records == []


def test_a_refused_key_neither_replaces_the_stored_key_nor_joins_the_rotation(client, fakes):
    add_openai(client)
    fakes.refused_key = "sk-wrong-key-0000"

    replaced = client.patch("/providers/openai", headers=ADMIN, json={"api_key": "sk-wrong-key-0000"})
    added = client.post("/providers/openai/keys", headers=ADMIN, json={"api_key": "sk-wrong-key-0000"})

    assert replaced.status_code == added.status_code == 422
    assert [key["last4"] for key in client.get("/providers", headers=ADMIN).json()[0]["keys"]] == ["7777"]


def test_the_check_asks_the_smallest_chat_model_the_provider_lists(client, fakes):
    add_openai(client)
    fakes.models = ["gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-5.4-nano", "gpt-5.4-nano-tts", "text-embedding-3-large"]

    result = client.post("/providers/openai/test", headers=ADMIN, json={}).json()

    assert result["model"] == "gpt-5.4-nano" and result["structured_output"] is True
    assert fakes.probed[0].model == "openai/gpt-5.4-nano"
    assert client.delete("/providers/nope", headers=ADMIN).status_code == 404


def test_models_are_listed_with_the_decrypted_key(client, fakes):
    add_openai(client)

    assert client.get("/providers/openai/models", headers=ADMIN).json() == {
        "provider_id": "openai", "models": ["gpt-5.4", "gpt-5.4-mini"],
    }
    assert fakes.listed_with == [KEY]


def test_a_failed_listing_is_a_bad_gateway_with_the_reason(client, fakes):
    add_openai(client)
    fakes.list_error = ModelListError("OpenAI returned HTTP 401 for its model list")

    response = client.get("/providers/openai/models", headers=ADMIN)

    assert response.status_code == 502 and "HTTP 401" in response.json()["detail"]


def test_the_test_call_lists_models_then_asks_the_fast_model_for_structured_output(client, fakes):
    add_openai(client)

    body = client.post("/providers/openai/test", headers=ADMIN, json={}).json()

    assert body == {"provider_id": "openai", "models": ["gpt-5.4", "gpt-5.4-mini"], "model": "gpt-5.4-mini",
                    "structured_output": True, "paid": True, "error": None}
    assert fakes.probed[0].model == "openai/gpt-5.4-mini" and fakes.probed[0].api_key == KEY


def test_a_model_that_fails_structured_output_is_reported_and_stays_usable(client, fakes):
    client.post("/providers", headers=ADMIN, json={"kind": "ollama", "base_url": "http://host.docker.internal:11434"})
    fakes.probe_error = LLMError("model ollama_chat/tiny replied with JSON that does not match ProbeReply")

    body = client.post("/providers/ollama/test", headers=ADMIN, json={"model": "tiny"}).json()

    assert (body["model"], body["structured_output"], body["paid"]) == ("tiny", False, False)
    assert "does not match" in body["error"]


def test_a_test_that_cannot_list_models_makes_no_call(client, fakes):
    add_openai(client)
    fakes.list_error = ModelListError("OpenAI did not answer: ConnectError")

    body = client.post("/providers/openai/test", headers=ADMIN, json={}).json()

    assert body["error"] == "OpenAI did not answer: ConnectError" and body["structured_output"] is False
    assert fakes.probed == []


def test_a_chat_tier_is_mapped_to_any_model_of_a_configured_provider(client, actions):
    add_openai(client)

    response = client.put("/models/tiers/sql-gen", headers=ADMIN, json={"provider_id": "openai", "model": "gpt-5.5"})

    assert response.json() == {"tier": "sql-gen", "provider_id": "openai", "model": "gpt-5.5", "eval": None,
                               "chain": [{"provider_id": "openai", "model": "gpt-5.5"}]}
    change = actions.records[-1]
    assert (change.action, change.target, change.old_value, change.new_value) == (
        "model_tier", "sql-gen", "openai/gpt-5.4", "openai/gpt-5.5",
    )


@pytest.mark.parametrize(("tier", "body", "code"), [
    ("embed", {"provider_id": "openai", "model": "text-embedding-3-small"}, 400),
    ("huge", {"provider_id": "openai", "model": "gpt-5.5"}, 404),
    ("fast", {"provider_id": "anthropic", "model": "claude-haiku-5-5"}, 422),
    ("fast", {"provider_id": "openai", "model": " "}, 422),
])
def test_a_tier_change_that_does_not_fit_is_refused(client, tier, body, code):
    add_openai(client)
    assert client.put(f"/models/tiers/{tier}", headers=ADMIN, json=body).status_code == code


def test_a_key_the_instance_key_cannot_read_asks_for_the_key_again(client, fakes, tmp_path):
    from app.state.secrets import SecretVault

    add_openai(client)
    db = app.dependency_overrides[setup_api.get_state_db]()
    app.dependency_overrides[providers_api.get_vault] = lambda: SecretVault(db, bytes([9]) * 32)

    for response in (client.get("/providers/openai/models", headers=ADMIN),
                     client.post("/providers/openai/test", headers=ADMIN, json={})):
        assert response.status_code == 409
        assert "enter it again" in response.json()["detail"]
    assert fakes.checked_with == [KEY] and fakes.listed_with == [] and fakes.probed == []


def test_changing_the_embedding_needs_a_confirmed_reindex(client):
    add_openai(client)
    change = {"backend": "provider", "provider_id": "openai", "model": "text-embedding-3-large", "dimensions": 1024}

    refused = client.put("/models/embedding", headers=ADMIN, json=change)

    assert refused.status_code == 409 and "full reindex" in refused.json()["detail"]
    assert client.get("/models/tiers", headers=ADMIN).json()["embedding"]["backend"] == "local"


def test_a_confirmed_embedding_change_marks_the_pack_as_needing_a_recompile(client, actions, fakes):
    add_openai(client)
    client.put("/models/embedding", headers=ADMIN, json={"backend": "provider", "provider_id": "openai",
               "model": "text-embedding-3-large", "dimensions": 1024, "confirm_reindex": True})
    fakes.compiled = ("openai/text-embedding-3-large", 1024)
    change = {"backend": "provider", "provider_id": "openai", "model": "text-embedding-3-small", "dimensions": 1536,
              "confirm_reindex": True}

    body = client.put("/models/embedding", headers=ADMIN, json=change).json()

    assert body == {"backend": "provider", "provider_id": "openai", "model": "text-embedding-3-small",
                    "dimensions": 1536, "needs_reindex": True}
    record = actions.records[-1]
    assert (record.action, record.old_value, record.new_value) == (
        "embedding", "openai/text-embedding-3-large", "openai/text-embedding-3-small",
    )


def test_the_embedding_can_move_back_to_a_local_model(client):
    body = client.put("/models/embedding", headers=ADMIN, json={
        "backend": "local", "model": "sentence-transformers/paraphrase-multilingual-mpnet-base-v2", "confirm_reindex": True,
    }).json()

    assert (body["backend"], body["dimensions"], body["needs_reindex"]) == ("local", 768, True)


@pytest.mark.parametrize("change", [
    {"backend": "local", "model": "someone/unknown-model"},
    {"backend": "provider", "provider_id": "nope", "model": "text-embedding-3-large", "dimensions": 1024},
    {"backend": "provider", "model": "text-embedding-3-large", "dimensions": 1024},
    {"backend": "provider", "provider_id": "openai", "model": "text-embedding-3-large", "dimensions": 0},
])
def test_an_embedding_change_that_does_not_fit_is_refused(client, change):
    add_openai(client)
    assert client.put("/models/embedding", headers=ADMIN, json={**change, "confirm_reindex": True}).status_code == 422


def test_adding_a_provider_answers_the_setups_models_step(client):
    add_openai(client)

    steps = {step["id"]: step["state"] for step in client.get("/setup/status", headers=ADMIN).json()["steps"]}

    assert steps["models"] == "done"


def test_each_tier_shows_the_latest_eval_result_of_its_model_without_limiting_the_choice(client):
    from datetime import datetime, UTC

    from app.llm.eligibility import ReportSummary

    add_openai(client)
    passed = ReportSummary("r1", datetime(2026, 11, 10, tzinfo=UTC), {"sql-gen": "openai/gpt-5.4"}, True, False)
    app.dependency_overrides[providers_api.get_eval_reports] = lambda: (lambda: [passed])

    tiers = {tier["tier"]: tier for tier in client.get("/models/tiers", headers=ADMIN).json()["tiers"]}

    assert tiers["sql-gen"]["eval"] == {"evaluated": True, "passed": True, "reason": "the latest eval report with it passed without regression",
                                        "report_id": "r1", "report_ts": "2026-11-10T00:00:00Z"}
    assert tiers["fast"]["eval"]["evaluated"] is False
    assert client.put("/models/tiers/fast", headers=ADMIN, json={"provider_id": "openai", "model": "gpt-5.5"}).status_code == 200


def test_the_provider_key_reaches_no_response_log_line_or_admin_action(client, actions, caplog):
    caplog.set_level(logging.DEBUG)
    bodies = [
        client.post("/providers", headers=ADMIN, json={"kind": "openai", "api_key": KEY}).text,
        client.get("/providers", headers=ADMIN).text,
        client.patch("/providers/openai", headers=ADMIN, json={"api_key": KEY + "-new"}).text,
        client.get("/providers/openai/models", headers=ADMIN).text,
        client.post("/providers/openai/test", headers=ADMIN, json={}).text,
    ]
    assert all("endpoint-key-7777" not in text for text in [*bodies, caplog.text, repr(actions.records)])


def test_an_ollama_provider_proposes_a_model_it_has_installed(client, fakes):
    fakes.models = ["deepseek-r1:8b", "llama3.1:8b", "nomic-embed-text:latest", "qwen2.5:3b"]

    assert client.post("/providers", headers=ADMIN, json={"kind": "ollama", "base_url": "http://host.docker.internal:11434"}).status_code == 201

    tiers = client.get("/models/tiers", headers=ADMIN).json()
    # The largest known model wins; a reasoning model of an unknown family is not proposed.
    assert {tier["model"] for tier in tiers["tiers"]} == {"llama3.1:8b"}
    assert tiers["embedding"]["model"] == "nomic-embed-text:latest"


@pytest.mark.parametrize(("installed", "proposed"), [
    (["qwen2.5:7b", "llama3.1:8b"], "llama3.1:8b"),
    (["qwen2.5-coder:7b", "qwen2.5:7b"], "qwen2.5-coder:7b"),
    (["phi4-mini:3.8b", "llama3.2:3b"], "phi4-mini:3.8b"),
    (["deepseek-r1:8b"], "deepseek-r1:8b"),
])
def test_the_proposed_ollama_model_is_the_largest_of_the_best_family(installed, proposed):
    from app.llm import defaults
    assert defaults.installed_chat_model(installed) == proposed


def test_an_ollama_provider_without_its_embedding_model_keeps_the_local_embedding(client, fakes):
    fakes.models = ["llama3.1:8b"]

    client.post("/providers", headers=ADMIN, json={"kind": "ollama", "base_url": "http://host.docker.internal:11434"})

    tiers = client.get("/models/tiers", headers=ADMIN).json()
    assert {tier["model"] for tier in tiers["tiers"]} == {"llama3.1:8b"}
    assert tiers["embedding"]["backend"] == "local"


def test_an_ollama_server_that_does_not_answer_is_not_added_and_the_reply_says_how_to_reach_it(client, fakes):
    fakes.list_error = ModelListError("Ollama did not answer: ConnectError")

    response = client.post("/providers", headers=ADMIN, json={"kind": "ollama", "base_url": "http://host.docker.internal:11434"})

    assert response.status_code == 422
    assert "OLLAMA_HOST=0.0.0.0" in response.json()["detail"] and "host-gateway" in response.json()["detail"]
    assert client.get("/providers", headers=ADMIN).json() == []


def test_an_ollama_server_without_a_chat_model_is_not_added(client, fakes):
    fakes.models = ["nomic-embed-text:latest"]

    response = client.post("/providers", headers=ADMIN, json={"kind": "ollama", "base_url": "http://host.docker.internal:11434"})

    assert response.status_code == 422 and "ollama pull" in response.json()["detail"]


class FakeCatalog:
    def __init__(self):
        self.asked: list = []

    def models(self, provider, api_key):
        from app.llm.catalog import CatalogModel

        self.asked.append((provider.id, api_key))
        return [
            CatalogModel(id="gpt-5.4", provider_id=provider.id, kind="chat", free="none", input_price=1.25,
                         output_price=10.0, context=400000, structured_output=True, benchmark=55.0),
            CatalogModel(id="text-embedding-3-small", provider_id=provider.id, kind="embedding", free="none"),
        ]


def test_the_catalog_describes_each_model_with_its_measured_latency(client):
    catalog = FakeCatalog()
    app.dependency_overrides[providers_api.get_catalog] = lambda: catalog
    app.dependency_overrides[providers_api.get_latency] = lambda: lambda: {("openai", "gpt-5.4"): 910, ("other", "gpt-5.4"): 5}
    add_openai(client)

    body = client.get("/models/catalog", headers=ADMIN, params={"provider": "openai"}).json()

    # Read once more by the automatic choice of the chains when the provider was added.
    assert catalog.asked[-1] == ("openai", KEY)
    assert body["provider_id"] == "openai"
    assert body["models"][0] == {
        "id": "gpt-5.4", "provider_id": "openai", "kind": "chat", "free": "none", "input_price": 1.25, "output_price": 10.0,
        "context": 400000, "structured_output": True, "benchmark": 55.0, "median_latency_ms": 910,
    }
    assert body["models"][1]["kind"] == "embedding" and body["models"][1]["median_latency_ms"] is None


def test_the_catalog_of_an_unknown_provider_is_not_found(client):
    app.dependency_overrides[providers_api.get_catalog] = lambda: FakeCatalog()
    app.dependency_overrides[providers_api.get_latency] = lambda: dict

    assert client.get("/models/catalog", headers=ADMIN, params={"provider": "nope"}).status_code == 404


def test_a_catalog_the_provider_does_not_list_is_a_bad_gateway(client):
    class Refusing:
        def models(self, provider, api_key):
            raise ModelListError("Groq returned HTTP 401 for its model list")

    app.dependency_overrides[providers_api.get_catalog] = lambda: Refusing()
    app.dependency_overrides[providers_api.get_latency] = lambda: dict
    add_openai(client)

    response = client.get("/models/catalog", headers=ADMIN, params={"provider": "openai"})

    assert response.status_code == 502 and "HTTP 401" in response.json()["detail"]



def catalog_with(models):
    from app.llm.catalog import CatalogModel

    class Fixed:
        def __init__(self):
            self.asked = []

        def models(self, provider, api_key):
            self.asked.append((provider.id, api_key))
            return [CatalogModel(provider_id=provider.id, **model) for model in models.get(provider.id, [])]

    return Fixed()


FREE_MODELS = {
    "openai": [
        {"id": "gpt-free", "kind": "chat", "free": "free_tier", "structured_output": True, "benchmark": 40.0},
        {"id": "gpt-paid", "kind": "chat", "free": "none", "structured_output": True, "benchmark": 70.0,
         "input_price": 1.0, "output_price": 4.0},
    ],
    "openai-compatible": [
        {"id": "lab-free", "kind": "chat", "free": "free", "structured_output": True, "benchmark": 30.0},
        {"id": "lab-loose", "kind": "chat", "free": "free", "structured_output": None, "benchmark": 50.0},
    ],
}


def add_lab(client):
    response = client.post("/providers", headers=ADMIN,
                           json={"kind": "openai_compatible", "base_url": "http://lab:1234/v1", "api_key": "lab-key-1"})
    assert response.status_code == 201, response.text


def test_a_provider_takes_more_keys_and_removes_them_one_at_a_time(client, actions):
    add_openai(client)

    added = client.post("/providers/openai/keys", headers=ADMIN, json={"api_key": "sk-second-8888", "label": "spare"})
    keys = added.json()["keys"]
    removed = client.delete(f"/providers/openai/keys/{keys[0]['id']}", headers=ADMIN)
    last = client.delete(f"/providers/openai/keys/{keys[1]['id']}", headers=ADMIN)

    assert added.status_code == 201 and [(key["label"], key["last4"]) for key in keys] == [("", "7777"), ("spare", "8888")]
    assert [key["last4"] for key in removed.json()["keys"]] == ["8888"]
    assert removed.json()["key_last4"] == "8888"
    assert last.status_code == 409 and "needs an API key" in last.json()["detail"]
    assert client.delete("/providers/openai/keys/nope", headers=ADMIN).status_code == 404
    logged = " ".join(f"{record.old_value} {record.new_value}" for record in actions.records)
    assert "sk-second-8888" not in logged and "8888" in logged


def test_a_tier_takes_a_whole_chain_and_shows_it_in_order(client):
    add_openai(client)
    add_lab(client)

    response = client.put("/models/tiers/sql-gen", headers=ADMIN, json={"chain": [
        {"provider_id": "openai-compatible", "model": "lab-free"}, {"provider_id": "openai", "model": "gpt-5.5"},
    ]})
    tiers = client.get("/models/tiers", headers=ADMIN).json()

    assert response.status_code == 200
    sql_gen = next(tier for tier in tiers["tiers"] if tier["tier"] == "sql-gen")
    assert (sql_gen["provider_id"], sql_gen["model"]) == ("openai-compatible", "lab-free")
    assert [link["model"] for link in sql_gen["chain"]] == ["lab-free", "gpt-5.5"]
    assert tiers["mode"] == "manual"
    bad = client.put("/models/tiers/sql-gen", headers=ADMIN, json={"chain": [{"provider_id": "nope", "model": "m"}]})
    assert bad.status_code == 422
    assert client.put("/models/tiers/sql-gen", headers=ADMIN, json={}).status_code == 422


def test_a_provider_that_shares_every_tier_with_another_can_be_removed(client):
    add_openai(client)
    add_lab(client)
    for tier in ("fast", "sql-small", "sql-gen", "sql-gen-hard"):
        client.put(f"/models/tiers/{tier}", headers=ADMIN, json={"chain": [
            {"provider_id": "openai", "model": "gpt-5.4"}, {"provider_id": "openai-compatible", "model": "lab-free"},
        ]})

    assert client.delete("/providers/openai-compatible", headers=ADMIN).status_code == 204
    tiers = client.get("/models/tiers", headers=ADMIN).json()["tiers"]
    assert {len(tier["chain"]) for tier in tiers} == {1}
    assert {tier["provider_id"] for tier in tiers} == {"openai"}


def test_auto_free_chooses_free_models_across_providers_and_a_manual_tier_ends_it(client):
    catalog = catalog_with(FREE_MODELS)
    app.dependency_overrides[providers_api.get_catalog] = lambda: catalog
    app.dependency_overrides[providers_api.get_latency] = lambda: dict
    add_openai(client)
    add_lab(client)

    body = client.put("/models/mode", headers=ADMIN, json={"mode": "auto_free"}).json()

    chains = {tier["tier"]: [(link["provider_id"], link["model"]) for link in tier["chain"]] for tier in body["tiers"]}
    assert body["mode"] == "auto_free" and body["refreshed_at"] is not None
    # fast needs structured output; the other tiers take a model that does not say.
    assert chains["fast"] == [("openai", "gpt-free"), ("openai-compatible", "lab-free")]
    assert chains["sql-gen"] == [("openai-compatible", "lab-loose"), ("openai", "gpt-free"), ("openai-compatible", "lab-free")]
    assert ("openai", KEY) in catalog.asked

    client.put("/models/tiers/fast", headers=ADMIN, json={"provider_id": "openai", "model": "gpt-paid"})
    assert client.get("/models/tiers", headers=ADMIN).json()["mode"] == "manual"


def test_auto_best_puts_the_best_benchmark_first(client):
    app.dependency_overrides[providers_api.get_catalog] = lambda: catalog_with(FREE_MODELS)
    app.dependency_overrides[providers_api.get_latency] = lambda: dict
    add_openai(client)
    add_lab(client)

    body = client.put("/models/mode", headers=ADMIN, json={"mode": "auto_best"}).json()

    fast = next(tier for tier in body["tiers"] if tier["tier"] == "fast")
    assert [link["model"] for link in fast["chain"]] == ["gpt-paid", "lab-free", "gpt-free"]
    assert client.put("/models/mode", headers=ADMIN, json={"mode": "fastest"}).status_code == 422


def test_a_new_instance_chooses_free_chains_by_itself_until_a_task_is_set_by_hand(client):
    assert client.get("/models/tiers", headers=ADMIN).json()["mode"] == "auto_free"
    add_openai(client)

    client.put("/models/tiers/fast", headers=ADMIN, json={"provider_id": "openai", "model": "gpt-5.4"})

    assert client.get("/models/tiers", headers=ADMIN).json()["mode"] == "manual"
