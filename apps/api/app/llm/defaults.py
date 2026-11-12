"""The model proposed for each tier when a provider is added (DECISIONS §2 Model tiers).

A proposal is only a starting point: the admin maps any tier to any model of a
configured provider afterwards. An OpenAI-compatible endpoint serves models
nobody can know in advance, so it proposes none and its tiers are chosen from
the models it lists. Anthropic has no embedding model.
"""

_CHAT = {
    "openai": {"fast": "gpt-5.4-mini", "sql-small": "gpt-5.4-mini", "sql-gen": "gpt-5.4", "sql-gen-hard": "gpt-5.5"},
    "anthropic": {
        "fast": "claude-haiku-5-5", "sql-small": "claude-haiku-5-5", "sql-gen": "claude-sonnet-5-5",
        "sql-gen-hard": "claude-opus-5-5",
    },
    "gemini": {
        "fast": "gemini-2.5-flash", "sql-small": "gemini-2.5-flash", "sql-gen": "gemini-2.5-pro",
        "sql-gen-hard": "gemini-2.5-pro",
    },
    "ollama": dict.fromkeys(("fast", "sql-small", "sql-gen", "sql-gen-hard"), "qwen2.5-coder:7b"),
    "openai_compatible": {},
}
_EMBEDDING = {"openai": "text-embedding-3-large", "gemini": "gemini-embedding-001", "ollama": "nomic-embed-text"}


def chat_models(kind: str) -> dict[str, str]:
    """The proposed model of each chat tier for a provider of ``kind``; empty when none can be proposed."""
    return dict(_CHAT.get(kind, {}))


def embedding_model(kind: str) -> str | None:
    return _EMBEDDING.get(kind)
