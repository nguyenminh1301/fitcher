"""The model proposed for each tier when a provider is added (DECISIONS §2 Model tiers).

A proposal is only a starting point: the admin maps any tier to any model of a
configured provider afterwards. An OpenAI-compatible endpoint serves models
nobody can know in advance, so it proposes none and its tiers are chosen from
the models it lists. A provider's embedding model is proposed for the embed
tier because the local models lost retrieval recall against it
(``docs/eval/local-embedding-report.md``); Anthropic has none, so with it
alone the embedding stays local. The OpenAI and Gemini embedding models return
the vector size they are asked for; Ollama's ``nomic-embed-text`` always
returns 768 floats.
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
# The local embedding model used while no connected provider offers one (DECISIONS §14).
LOCAL_EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
_EMBEDDING = {"openai": "text-embedding-3-large", "gemini": "gemini-embedding-001", "ollama": "nomic-embed-text"}
# The vector size of an embedding model that cannot return another size.
_FIXED_DIMENSIONS = {"nomic-embed-text": 768}
# The vector size asked of each proposed embedding model; 1024 is what packs indexed before the app state used.
_PROPOSED_DIMENSIONS = {"text-embedding-3-large": 1024, "gemini-embedding-001": 768, **_FIXED_DIMENSIONS}


def chat_models(kind: str) -> dict[str, str]:
    """The proposed model of each chat tier for a provider of ``kind``; empty when none can be proposed."""
    return dict(_CHAT.get(kind, {}))


def embedding_model(kind: str) -> str | None:
    return _EMBEDDING.get(kind)


def fixed_dimensions(model: str) -> int | None:
    """The only vector size ``model`` returns, or None when it returns the size it is asked for."""
    return _FIXED_DIMENSIONS.get(model)


def proposed_dimensions(model: str) -> int | None:
    """The vector size proposed for an embedding model of ``embedding_model``."""
    return _PROPOSED_DIMENSIONS.get(model)
