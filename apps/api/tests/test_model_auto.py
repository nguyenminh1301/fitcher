"""The automatic choice of each chat tier's chain from a fixed catalog."""

from datetime import datetime, timedelta, UTC

import pytest
from state_fixtures import new_state

from app.llm import auto
from app.llm.catalog import CatalogModel, ModelListError
from app.llm.providers import ProviderStore
from app.llm.routes import TierMapping, TierModel


def model(provider: str, name: str, *, free: str = "free", benchmark: float | None = None, latency: int | None = None,
          structured: bool | None = True, kind: str = "chat", price: float | None = None) -> CatalogModel:
    return CatalogModel(id=name, provider_id=provider, kind=kind, free=free, benchmark=benchmark,
                        median_latency_ms=latency, structured_output=structured, input_price=price, output_price=price)


CATALOG = [
    model("groq", "groq-a", free="free_tier", benchmark=40, latency=900),
    model("groq", "groq-b", free="free_tier", benchmark=40, latency=300),
    model("groq", "groq-c", free="free_tier", benchmark=20),
    model("gemini", "gemini-a", free="free_tier", benchmark=30),
    model("zai", "zai-a", benchmark=35, structured=None),
    model("router", "router-paid", free="none", benchmark=90, price=1.0),
    model("router", "router-cheap", free="none", benchmark=90, price=0.1),
    model("router", "router-free", benchmark=None),
    model("gemini", "gemini-embed", kind="embedding", free="free_tier"),
    model("groq", "guard", kind="other", free="free_tier", benchmark=99),
]


def chain(tier_models):
    return [(link.provider_id, link.model) for link in tier_models]


def test_auto_free_ranks_free_models_by_benchmark_then_latency_and_spreads_providers():
    chosen = auto.choose(CATALOG, "auto_free")

    assert chain(chosen["fast"]) == [("groq", "groq-b"), ("gemini", "gemini-a"), ("router", "router-free"), ("groq", "groq-a")]
    assert chain(chosen["sql-gen"]) == [("groq", "groq-b"), ("zai", "zai-a"), ("gemini", "gemini-a"), ("router", "router-free")]


def test_auto_best_takes_any_chat_model_and_the_cheaper_one_on_a_tie():
    chosen = auto.choose(CATALOG, "auto_best")

    assert chain(chosen["sql-gen"])[:2] == [("router", "router-cheap"), ("groq", "groq-a")]


def test_the_quick_tiers_put_small_fast_models_first_and_leave_out_reasoning_models():
    catalog = [
        model("gemini", "gemini-3.8-flash", free="free_tier", benchmark=60, latency=9000),
        model("gemini", "gemini-flash-lite-latest", free="free_tier", benchmark=40, latency=800),
        model("groq", "openai/gpt-oss-20b", free="free_tier", benchmark=35, latency=400),
        model("router", "nemotron-nano-reasoning:free", benchmark=50),
        model("zai", "glm-4.5-flash", benchmark=30),
    ]

    chosen = auto.choose(catalog, "auto_free")

    assert chain(chosen["fast"]) == [("gemini", "gemini-flash-lite-latest"), ("zai", "glm-4.5-flash"),
                                     ("groq", "openai/gpt-oss-20b"), ("gemini", "gemini-3.8-flash")]
    assert chain(chosen["sql-gen"])[0] == ("gemini", "gemini-3.8-flash")


def test_a_model_known_not_to_follow_a_schema_serves_no_tier():
    chosen = auto.choose([model("zai", "zai-a", structured=False)], "auto_free")

    assert chosen == {}


@pytest.fixture
def mapping(tmp_path):
    db, vault = new_state(tmp_path)
    store = ProviderStore(db, vault)
    store.create("openai", api_key="sk-test-1111")
    store.create("openai_compatible", base_url="http://lab:1234/v1")
    return TierMapping(db, store), store


def test_refresh_applies_the_choice_once_a_day_and_never_in_manual_mode(mapping):
    tiers, store = mapping
    tiers.set_mode("manual")
    tiers.set_tier("fast", "openai", "kept")
    catalog = {"openai": [model("openai", "gpt-free", benchmark=50)],
               "openai-compatible": [model("openai-compatible", "lab", benchmark=10)]}
    asked = []

    def listing(provider):
        asked.append(provider.id)
        return catalog[provider.id]

    now = datetime(2026, 11, 19, 8, tzinfo=UTC)
    assert not auto.refresh(tiers, store.list(), listing, {}, force=True, now=now)
    assert tiers.chain("fast") == [TierModel("openai", "kept")]

    tiers.set_mode("auto_free")
    assert auto.refresh(tiers, store.list(), listing, {("openai", "gpt-free"): 700}, now=now)
    assert tiers.chain("fast") == [TierModel("openai", "gpt-free"), TierModel("openai-compatible", "lab")]
    assert tiers.mode() == ("auto_free", now)
    assert not auto.refresh(tiers, store.list(), listing, {}, now=now + timedelta(hours=23))
    assert auto.refresh(tiers, store.list(), listing, {}, now=now + timedelta(hours=25))
    assert asked.count("openai") == 2


def test_a_provider_that_does_not_list_its_models_is_left_out(mapping):
    tiers, store = mapping
    tiers.set_mode("auto_free")

    def listing(provider):
        if provider.id == "openai":
            raise ModelListError("OpenAI returned HTTP 401 for its model list")
        return [model(provider.id, "lab")]

    assert auto.refresh(tiers, store.list(), listing, {}, force=True)
    assert tiers.chain("fast") == [TierModel("openai-compatible", "lab")]
