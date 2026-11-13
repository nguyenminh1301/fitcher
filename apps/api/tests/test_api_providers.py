"""The provider and tier endpoints over a temporary app state; listing and the test call are fakes."""

from fastapi.testclient import TestClient
import pytest

from auth_fixtures import token, verifier
from state_fixtures import new_state

from app.api import providers as providers_api, runtime, setup as setup_api
from app.llm.client import LLMError
from app.llm.provider_models import ModelListError
from app.main import app

ADMIN = {"Authorization": f"Bearer {token(preferred_username='lab.admin', realm_access={'roles': ['admin']})}"}
VIEWER = {"Authorization": f"Bearer {token()}"}
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
        self.list_error: ModelListError | None = None
        self.probed: list = []
        self.probe_error: LLMError | None = None
        self.compiled: tuple[str, int] | None = ("local/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", 384)

    def lister(self, provider, api_key):
        self.listed_with.append(api_key)
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
    app.dependency_overrides[runtime.get_verifier] = lambda: verifier()
    app.dependency_overrides[setup_api.get_state_db] = lambda: db
    app.dependency_overrides[providers_api.get_vault] = lambda: vault
    app.dependency_overrides[providers_api.get_model_lister] = lambda: fakes.lister
    app.dependency_overrides[providers_api.get_probe] = lambda: fakes.probe
    app.dependency_overrides[runtime.get_admin_action_log] = lambda: actions
    app.dependency_overrides[providers_api.get_compiled_embedding] = lambda: fakes.compiled
    yield TestClient(app)
    app.dependency_overrides.clear()


def add_openai(client):
    response = client.post("/providers", headers=ADMIN, json={"kind": "openai", "api_key": KEY})
    assert response.status_code == 201, response.text
    return response


@pytest.mark.parametrize(("method", "path"), [
    ("get", "/providers"), ("post", "/providers"), ("patch", "/providers/openai"), ("delete", "/providers/openai"),
    ("get", "/providers/openai/models"), ("post", "/providers/openai/test"), ("get", "/models/tiers"),
    ("put", "/models/tiers/fast"), ("put", "/models/embedding"),
])
def test_every_endpoint_needs_the_admin_role(client, method, path):
    assert getattr(client, method)(path, headers=VIEWER).status_code == 403


def test_adding_the_first_provider_shows_only_the_key_ending_and_fills_the_tiers(client, actions):
    body = add_openai(client).json()

    assert body == {"id": "openai", "name": "OpenAI", "kind": "openai", "base_url": None, "key_set": True,
                    "key_last4": "7777", "hosted": True, "in_use": True}
    tiers = client.get("/models/tiers", headers=ADMIN).json()
    fast = tiers["tiers"][0]
    assert (fast["tier"], fast["provider_id"], fast["model"], fast["eval"]["evaluated"]) == ("fast", "openai", "gpt-5.4-mini", False)
    # The pack was indexed locally, so the provider's embedding model now needs a recompile.
    assert tiers["embedding"] == {"backend": "provider", "provider_id": "openai", "model": "text-embedding-3-large",
                                  "dimensions": 1024, "needs_reindex": True}
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


def test_a_provider_in_use_cannot_be_removed(client):
    add_openai(client)
    assert client.post("/providers", headers=ADMIN, json={"kind": "gemini", "api_key": KEY}).json()["in_use"] is False

    assert client.delete("/providers/gemini", headers=ADMIN).status_code == 204
    refused = client.delete("/providers/openai", headers=ADMIN)
    assert refused.status_code == 409 and "in use" in refused.json()["detail"]
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

    assert response.json() == {"tier": "sql-gen", "provider_id": "openai", "model": "gpt-5.5", "eval": None}
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
    assert fakes.listed_with == [] and fakes.probed == []



def test_changing_the_embedding_needs_a_confirmed_reindex(client):
    add_openai(client)
    change = {"backend": "local", "model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"}

    refused = client.put("/models/embedding", headers=ADMIN, json=change)

    assert refused.status_code == 409 and "full reindex" in refused.json()["detail"]
    assert client.get("/models/tiers", headers=ADMIN).json()["embedding"]["backend"] == "provider"


def test_a_confirmed_embedding_change_marks_the_pack_as_needing_a_recompile(client, actions, fakes):
    add_openai(client)
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
