"""The LiteLLM embedding client and environment settings, without network access."""

import json

import httpx
import pytest

from app.config import SettingsError, load_settings
from app.llm.embeddings import EmbeddingError, LiteLLMEmbeddings


def client(handler, dimensions: int = 3) -> LiteLLMEmbeddings:
    return LiteLLMEmbeddings("http://litellm:4000/", "sk-test", dimensions, http=httpx.Client(transport=httpx.MockTransport(handler)))


def test_embeddings_call_the_embed_alias_with_the_configured_dimensions():
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append({"url": str(request.url), "auth": request.headers["Authorization"], **body})
        data = [{"index": index, "embedding": [float(index)] * 3} for index in reversed(range(len(body["input"])))]
        return httpx.Response(200, json={"data": data})

    vectors = client(handler).embed(["a", "b"])

    assert vectors == [[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]]
    assert requests == [{
        "url": "http://litellm:4000/v1/embeddings", "auth": "Bearer sk-test",
        "model": "embed", "input": ["a", "b"], "dimensions": 3,
    }]


def test_embeddings_are_sent_in_batches():
    sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        inputs = json.loads(request.content)["input"]
        sizes.append(len(inputs))
        return httpx.Response(200, json={"data": [{"index": i, "embedding": [0.0] * 3} for i in range(len(inputs))]})

    assert len(client(handler).embed(["x"] * 600)) == 600
    assert sizes == [256, 256, 88]


def test_wrong_vector_size_is_rejected():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.0] * 5}]})

    with pytest.raises(EmbeddingError, match="returned 5 dimensions; EMBEDDING_DIMENSIONS is 3"):
        client(handler).embed(["a"])


def test_http_error_names_the_alias_and_status_only():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid key sk-secret"})

    with pytest.raises(EmbeddingError) as raised:
        client(handler).embed(["a"])

    assert str(raised.value) == "alias embed returned HTTP 401"


def test_missing_gateway_settings_are_rejected():
    with pytest.raises(EmbeddingError, match="LITELLM_BASE_URL and LITELLM_MASTER_KEY must be set"):
        LiteLLMEmbeddings("http://litellm:4000", "", 3)


def test_settings_defaults():
    settings = load_settings({})

    assert settings.qdrant_url == "http://qdrant:6333"
    assert settings.embedding_dimensions == 1024
    assert settings.column_values_top_k == 10_000
    assert settings.compiled_pack_dir == "build/packs"


@pytest.mark.parametrize("value", ["abc", "0", "-5"])
def test_invalid_numeric_setting_is_rejected(value):
    with pytest.raises(SettingsError, match="EMBEDDING_DIMENSIONS"):
        load_settings({"EMBEDDING_DIMENSIONS": value})


def test_screening_settings_default_to_log_mode_and_the_plan_thresholds():
    settings = load_settings({})
    assert (settings.screen_mode, settings.screen_flag_at, settings.screen_block_at, settings.guard_model_dir) == (
        "log", 0.5, 0.9, "build/guard_model",
    )


@pytest.mark.parametrize(("env", "message"), [
    ({"SCREEN_MODE": "strict"}, "SCREEN_MODE must be one of log, enforce"),
    ({"SCREEN_FLAG_AT": "high"}, "SCREEN_FLAG_AT must be a number"),
    ({"SCREEN_BLOCK_AT": "1.5"}, "SCREEN_BLOCK_AT must be above 0 and at most 1"),
    ({"SCREEN_FLAG_AT": "0.95", "SCREEN_BLOCK_AT": "0.9"}, "must not be above SCREEN_BLOCK_AT"),
])
def test_invalid_screening_settings_are_rejected(env, message):
    with pytest.raises(SettingsError, match=message):
        load_settings(env)
