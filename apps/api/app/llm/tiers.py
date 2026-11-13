"""The model tiers engine code calls (DECISIONS §2 Model tiers).

Each tier maps to a model of a configured provider in the app state
(``app/llm/routes.py``). ``MODEL_TIER_<TIER>`` and the catalog aliases below
belong to the LiteLLM Proxy era; bootstrap reads them once to keep a mapping
made before the app state existed.
"""

from collections.abc import Mapping

CHAT_TIERS = ("fast", "sql-small", "sql-gen", "sql-gen-hard")
EMBED_TIER = "embed"
TIERS = (*CHAT_TIERS, EMBED_TIER)
# Aliases of the OpenAI catalog block, used when a MODEL_TIER_<TIER> setting is empty.
BUILT_IN_DEFAULTS = {
    "fast": "openai-small",
    "sql-small": "openai-small",
    "sql-gen": "openai-medium",
    "sql-gen-hard": "openai-large",
    "embed": "openai-embed",
}

def setting_name(tier: str) -> str:
    return "MODEL_TIER_" + tier.upper().replace("-", "_")


def tier_defaults(env: Mapping[str, str]) -> dict[str, str]:
    """The default alias of every tier from ``MODEL_TIER_<TIER>``, else the built-in default."""
    return {tier: env.get(setting_name(tier)) or BUILT_IN_DEFAULTS[tier] for tier in TIERS}


def provider_of(alias: str) -> str:
    """The provider an alias belongs to: catalog aliases are named ``<provider>-<size>``."""
    return alias.split("-", 1)[0]


def check_chat_tier(tier: str) -> None:
    if tier not in CHAT_TIERS:
        raise ValueError(f"unknown chat tier {tier!r}; use one of {list(CHAT_TIERS)}")
