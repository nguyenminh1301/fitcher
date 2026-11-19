"""The model catalog built from recorded listings of each provider shape; no request leaves the test."""

import json
from pathlib import Path

import pytest

from app.llm.catalog import benchmark_index, build, Catalog, service_of, TTL_SECONDS, with_latency
from app.llm.providers import Provider

FIXTURES = Path(__file__).parent / "fixtures" / "catalog"
# A slice of LiteLLM's price table, in its shape, so the tests do not follow the bundled table's updates.
PRICES = {
    "gemini/gemini-2.5-flash": {"mode": "chat", "input_cost_per_token": 3e-07, "output_cost_per_token": 2.5e-06,
                                "max_input_tokens": 1048576, "supports_response_schema": True},
    "gemini/gemini-embedding-001": {"mode": "embedding", "input_cost_per_token": 1.5e-07, "output_cost_per_token": 0},
    "zai/glm-4.6": {"mode": "chat", "input_cost_per_token": 6e-07, "output_cost_per_token": 2.2e-06, "max_input_tokens": 200000},
    "zai/glm-5.3-flash": {"mode": "chat", "input_cost_per_token": 1.5e-07, "output_cost_per_token": 5e-07},
    "gpt-x": {"mode": "chat", "input_cost_per_token": 1e-06, "output_cost_per_token": 4e-06, "supports_response_schema": True},
    "text-embedding-x": {"mode": "embedding", "input_cost_per_token": 2e-08},
    "groq/whisper-large-v3": {"mode": "audio_transcription"},
}


def listing(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def provider(kind: str, base_url: str | None = None, provider_id: str | None = None) -> Provider:
    return Provider(provider_id or kind, kind, kind, base_url, True, "abcd")


GEMINI = provider("gemini")
GROQ = provider("openai_compatible", "https://api.groq.com/openai/v1", "groq")
ZAI = provider("openai_compatible", "https://api.z.ai/api/paas/v4", "zai")
OPENROUTER = provider("openai_compatible", "https://openrouter.ai/api/v1", "openrouter")
BENCHMARKS = benchmark_index(listing("openrouter"))


def by_id(models):
    return {model.id: model for model in models}


def test_providers_are_recognised_by_kind_or_by_the_host_of_their_endpoint():
    assert [service_of(item) for item in (GEMINI, GROQ, ZAI, OPENROUTER)] == ["gemini", "groq", "zai", "openrouter"]
    assert service_of(provider("openai_compatible", "http://host.docker.internal:1234/v1")) == "custom"
    assert service_of(provider("openai_compatible", "https://api.groq.com.example.net/v1")) == "custom"


def test_gemini_chat_models_generate_content_and_speech_image_and_live_models_are_other():
    models = by_id(build(GEMINI, listing("gemini"), price_table=PRICES, benchmarks=BENCHMARKS))

    kinds = {name: model.kind for name, model in models.items()}
    assert kinds == {
        "gemini-2.5-flash": "chat", "gemini-2.5-pro": "chat", "gemma-4-31b-it": "chat",
        "gemini-embedding-001": "embedding", "gemini-2.5-flash-preview-tts": "other", "gemini-2.5-flash-image": "other",
        "gemini-3.1-flash-live-preview": "other", "aqa": "other",
    }
    flash = models["gemini-2.5-flash"]
    assert (flash.free, flash.input_price, flash.output_price, flash.context, flash.structured_output) == (
        "free_tier", 0.3, 2.5, 1048576, True)
    assert models["gemini-2.5-pro"].free == "none"
    assert models["gemma-4-31b-it"].structured_output is False
    assert models["gemma-4-31b-it"].benchmark == BENCHMARKS["gemma-4-31b-it"]
    assert models["gemini-embedding-001"].free == "free_tier" and models["gemini-embedding-001"].benchmark is None
    assert list(models)[:3] == ["gemini-2.5-flash", "gemini-2.5-pro", "gemma-4-31b-it"]


def test_groq_lists_prices_and_context_and_its_classifier_and_speech_models_are_other():
    models = by_id(build(GROQ, listing("groq"), price_table=PRICES, benchmarks=BENCHMARKS))

    gpt = models["openai/gpt-oss-120b"]
    assert (gpt.kind, gpt.free, gpt.input_price, gpt.output_price, gpt.context) == ("chat", "free_tier", 0.15, 0.6, 131072)
    assert gpt.benchmark == BENCHMARKS["openai/gpt-oss-120b"]
    assert models["meta-llama/llama-prompt-guard-2-86m"].kind == "other"
    assert models["whisper-large-v3"].kind == "other" and models["whisper-large-v3"].free == "none"
    assert models["allam-2-7b"].kind == "chat"


def test_only_the_known_free_zai_models_are_free_and_the_unlisted_one_is_added():
    models = by_id(build(ZAI, listing("zai"), price_table=PRICES, benchmarks=BENCHMARKS))

    assert models["glm-4.5-flash"].free == "free" and models["glm-4.5-flash"].structured_output is True
    assert models["glm-5.3-flash"].free == "none" and models["glm-5.3-flash"].input_price == 0.15
    assert models["glm-5.3-flashx"].free == "none" and models["glm-5.3-flashx"].input_price is None
    assert (models["glm-4.6"].input_price, models["glm-4.6"].context) == (0.6, 200000)
    # OpenRouter lists glm-4.6 without a benchmark, so none is invented.
    assert models["glm-4.6"].benchmark is None


def test_openrouter_free_models_parameters_and_benchmarks_come_from_its_listing():
    models = by_id(build(OPENROUTER, listing("openrouter"), price_table=PRICES, benchmarks=BENCHMARKS))

    free = models["google/gemma-4-31b-it:free"]
    assert (free.kind, free.free, free.input_price, free.output_price) == ("chat", "free", 0.0, 0.0)
    assert free.structured_output is True
    assert models["cohere/north-mini-code:free"].structured_output is False
    assert models["openai/gpt-oss-120b"].free == "none"
    assert models["openai/gpt-oss-120b"].benchmark is not None
    assert models["example/voice-model"].kind == "other"


def test_other_kinds_take_price_and_mode_from_the_price_table_only_for_known_providers():
    body = {"data": [{"id": "gpt-x"}, {"id": "text-embedding-x"}, {"id": "tts-x"}]}

    hosted = by_id(build(provider("openai"), body, price_table=PRICES, benchmarks={}))
    custom = by_id(build(provider("openai_compatible", "http://host.docker.internal:8000/v1"), body,
                         price_table=PRICES, benchmarks={}))

    assert (hosted["gpt-x"].input_price, hosted["gpt-x"].structured_output) == (1.0, True)
    assert hosted["text-embedding-x"].kind == "embedding" and hosted["tts-x"].kind == "other"
    # A server on this network that reports a known name is not priced as that model.
    assert custom["gpt-x"].input_price is None and custom["gpt-x"].structured_output is None
    assert custom["gpt-x"].free == "none"


def test_a_model_server_on_this_computer_is_free():
    ollama = provider("ollama", "http://host.docker.internal:11434")
    models = by_id(build(ollama, {"models": [{"name": "qwen2.5:7b"}, {"name": "nomic-embed-text"}]},
                         price_table=PRICES, benchmarks={}))

    assert {name: (model.kind, model.free) for name, model in models.items()} == {
        "qwen2.5:7b": ("chat", "free"), "nomic-embed-text": ("embedding", "free"),
    }


def test_measured_latency_is_added_by_model_name():
    models = build(GROQ, listing("groq"), price_table=PRICES, benchmarks={})

    timed = by_id(with_latency(models, {"openai/gpt-oss-120b": 840}))

    assert timed["openai/gpt-oss-120b"].median_latency_ms == 840
    assert timed["allam-2-7b"].median_latency_ms is None


def test_the_catalog_is_kept_per_provider_and_key_for_six_hours():
    calls, now = [], [0.0]

    def fetch(item, api_key):
        calls.append((item.id, api_key))
        return listing("zai")

    catalog = Catalog(listing=fetch, reference=lambda: None, price_table=lambda: PRICES, clock=lambda: now[0])

    catalog.models(ZAI, "key-1")
    now[0] = TTL_SECONDS - 1
    catalog.models(ZAI, "key-1")
    assert len(calls) == 1
    replaced = Provider(ZAI.id, ZAI.name, ZAI.kind, ZAI.base_url, True, "wxyz")
    catalog.models(replaced, "key-2")
    assert len(calls) == 2
    now[0] = TTL_SECONDS * 2
    catalog.models(ZAI, "key-1")
    assert calls[-1] == ("zai", "key-1") and len(calls) == 3


def test_an_unreadable_reference_list_leaves_benchmarks_empty():
    assert benchmark_index(None) == {}
    assert benchmark_index({"data": [{"id": "x/y"}, "junk"]}) == {}


@pytest.mark.parametrize("body", [{"data": "nope"}, {"models": None}])
def test_an_unknown_listing_shape_is_refused(body):
    from app.llm.provider_models import ModelListError

    with pytest.raises(ModelListError):
        build(GEMINI if "models" in body else GROQ, body, price_table={}, benchmarks={})


def test_zai_s_free_model_is_in_its_catalog_although_zai_does_not_list_it():
    body = {"data": [{"id": "glm-5.3-flash"}, {"id": "glm-4.6"}]}

    models = by_id(build(ZAI, body, price_table={}, benchmarks={}))

    assert models["glm-4.5-flash"].free == "free" and models["glm-4.5-flash"].kind == "chat"
    assert models["glm-5.3-flash"].free == "none"
