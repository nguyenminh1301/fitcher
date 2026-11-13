"""Tier defaults, the cached tier-to-alias mapping and the LiteLLM catalog it points into."""

import importlib.util
from pathlib import Path

import pytest
import yaml

from app.llm.tiers import BUILT_IN_DEFAULTS, provider_of, TIERS, tier_defaults

ROOT = Path(__file__).resolve().parents[3]
LITELLM = ROOT / "infra" / "litellm"





def test_defaults_come_from_the_environment_with_built_in_fallbacks():
    defaults = tier_defaults({"MODEL_TIER_SQL_SMALL": "local-small", "MODEL_TIER_FAST": ""})

    assert defaults["sql-small"] == "local-small"
    assert defaults["fast"] == BUILT_IN_DEFAULTS["fast"]
    assert set(defaults) == set(TIERS)


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
