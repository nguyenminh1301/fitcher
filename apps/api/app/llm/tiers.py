"""The model tiers engine code calls (DECISIONS §2 Model tiers).

Each tier maps to a model of a configured provider in the app state
(``app/llm/routes.py``). ``MODEL_TIER_<TIER>`` and the ``<provider>-<size>``
catalog aliases belong to the LiteLLM Proxy era: bootstrap reads them once to
keep a mapping made before the app state existed, and old ``llm_calls`` rows
name their provider through the alias.
"""


CHAT_TIERS = ("fast", "sql-small", "sql-gen", "sql-gen-hard")
EMBED_TIER = "embed"
TIERS = (*CHAT_TIERS, EMBED_TIER)


def setting_name(tier: str) -> str:
    return "MODEL_TIER_" + tier.upper().replace("-", "_")


def provider_of(alias: str) -> str:
    """The provider an alias belongs to: catalog aliases are named ``<provider>-<size>``."""
    return alias.split("-", 1)[0]


def check_chat_tier(tier: str) -> None:
    if tier not in CHAT_TIERS:
        raise ValueError(f"unknown chat tier {tier!r}; use one of {list(CHAT_TIERS)}")
