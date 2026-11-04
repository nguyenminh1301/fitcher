"""Tier defaults, the cached tier-to-alias mapping and the LiteLLM catalog it points into."""

import importlib.util
from pathlib import Path

import pytest
import yaml

from app.llm.tiers import (
    BUILT_IN_DEFAULTS, CACHE_SECONDS, TIERS, TierMap, TierStoreError, provider_of, tier_defaults,
)

ROOT = Path(__file__).resolve().parents[3]
LITELLM = ROOT / "infra" / "litellm"


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class FakeTierStore:
    def __init__(self, rows: dict[str, str] | None = None):
        self.rows = dict(rows or {})
        self.reads = 0
        self.fail = False

    def read(self) -> dict[str, str]:
        self.reads += 1
        if self.fail:
            raise TierStoreError("clickhouse is down")
        return dict(self.rows)

    def write(self, tier, alias, changed_by, changed_at):
        self.rows[tier] = alias


def test_defaults_come_from_the_environment_with_built_in_fallbacks():
    defaults = tier_defaults({"MODEL_TIER_SQL_SMALL": "local-small", "MODEL_TIER_FAST": ""})

    assert defaults["sql-small"] == "local-small"
    assert defaults["fast"] == BUILT_IN_DEFAULTS["fast"]
    assert set(defaults) == set(TIERS)


def test_without_a_store_every_tier_keeps_its_default():
    tiers = TierMap(BUILT_IN_DEFAULTS)

    assert [tiers.alias(tier) for tier in TIERS] == [BUILT_IN_DEFAULTS[tier] for tier in TIERS]


def test_a_stored_mapping_wins_and_a_change_is_read_within_the_cache_window():
    clock, store = Clock(), FakeTierStore({"sql-small": "anthropic-small"})
    tiers = TierMap(BUILT_IN_DEFAULTS, store, clock=clock)

    assert tiers.alias("sql-small") == "anthropic-small"
    store.rows["sql-small"] = "gemini-small"
    clock.now = CACHE_SECONDS - 1
    assert tiers.alias("sql-small") == "anthropic-small"
    clock.now = CACHE_SECONDS
    assert tiers.alias("sql-small") == "gemini-small"
    assert store.reads == 2


def test_the_cache_window_is_at_most_thirty_seconds():
    assert CACHE_SECONDS <= 30


def test_invalidate_reads_the_store_on_the_next_lookup():
    store = FakeTierStore()
    tiers = TierMap(BUILT_IN_DEFAULTS, store, clock=Clock())
    tiers.alias("fast")
    store.rows["fast"] = "openai-medium"

    tiers.invalidate()

    assert tiers.alias("fast") == "openai-medium"


def test_a_stored_embed_row_never_changes_the_embedding_alias():
    tiers = TierMap(BUILT_IN_DEFAULTS, FakeTierStore({"embed": "gemini-embed"}), clock=Clock())

    assert tiers.alias("embed") == BUILT_IN_DEFAULTS["embed"]


def test_an_unreadable_store_keeps_the_last_mapping():
    clock, store = Clock(), FakeTierStore({"sql-gen": "anthropic-medium"})
    tiers = TierMap(BUILT_IN_DEFAULTS, store, clock=clock)
    tiers.alias("sql-gen")
    store.fail = True
    clock.now = CACHE_SECONDS * 2

    assert tiers.alias("sql-gen") == "anthropic-medium"


def test_an_unknown_tier_or_missing_default_is_refused():
    with pytest.raises(ValueError, match="unknown tier"):
        TierMap(BUILT_IN_DEFAULTS).alias("gpt-5.4")
    with pytest.raises(ValueError, match="no default alias"):
        TierMap({"fast": "openai-small"})


def test_provider_is_the_alias_prefix():
    assert [provider_of(alias) for alias in ("openai-small", "anthropic-medium", "local-small")] == [
        "openai", "anthropic", "local",
    ]


# LiteLLM catalog

def load_build_config():
    spec = importlib.util.spec_from_file_location("build_config", LITELLM / "build_config.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build_config = load_build_config()
BLOCKS = build_config.load_blocks(LITELLM / "catalog")
BASE = yaml.safe_load((LITELLM / "config.yaml").read_text(encoding="utf-8"))
ALL_KEYS = {"OPENAI_API_KEY": "k", "ANTHROPIC_API_KEY": "k", "GEMINI_API_KEY": "k", "OLLAMA_URL": "http://ollama:11434"}


def test_the_catalog_offers_openai_anthropic_gemini_and_a_local_model():
    _, aliases = build_config.build(BASE, BLOCKS, ALL_KEYS)

    assert {provider_of(alias) for alias in aliases} == {"openai", "anthropic", "gemini", "local"}
    assert len(aliases) == len(set(aliases))


def test_every_alias_is_named_for_its_provider_and_size_and_needs_its_own_variables():
    for block in BLOCKS:
        assert block["requires"]
        for model in block["model_list"]:
            provider, size = model["model_name"].split("-", 1)
            assert size in {"small", "medium", "large", "embed"}
            referenced = [value for value in model["litellm_params"].values() if str(value).startswith("os.environ/")]
            assert {value.removeprefix("os.environ/") for value in referenced} <= set(block["requires"])


def test_a_provider_without_its_key_is_not_loaded():
    config, aliases = build_config.build(BASE, BLOCKS, {"OPENAI_API_KEY": "k", "ANTHROPIC_API_KEY": ""})

    assert aliases and all(provider_of(alias) == "openai" for alias in aliases)
    assert config["general_settings"] == BASE["general_settings"]
    assert config["guardrails"] == BASE["guardrails"]


def test_no_key_starts_the_gateway_with_an_empty_catalog():
    config, aliases = build_config.build(BASE, BLOCKS, {})

    assert aliases == [] and config["model_list"] == []


def test_the_default_of_every_tier_is_a_catalog_alias():
    _, aliases = build_config.build(BASE, BLOCKS, ALL_KEYS)

    assert set(BUILT_IN_DEFAULTS.values()) <= set(aliases)
