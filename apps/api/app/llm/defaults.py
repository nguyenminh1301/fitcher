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

import re

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


# Ollama model families, best first, for proposing a chat model among the models a server has installed:
# code-tuned and instruction-following models write SQL and structured replies best.
OLLAMA_CHAT_FAMILIES = ("qwen2.5-coder", "qwen3-coder", "qwen3", "qwen2.5", "llama3.3", "llama3.1", "mistral-small",
                        "mistral", "gemma3", "phi4", "phi4-mini", "llama3.2")
# Ollama embedding model families; they cannot chat, so they are never proposed for a chat tier.
OLLAMA_EMBEDDING_FAMILIES = ("nomic-embed-text", "mxbai-embed-large", "bge-m3", "snowflake-arctic-embed", "all-minilm")


def _family(name: str) -> str:
    return name.partition(":")[0].rpartition("/")[2]


def _billions(name: str) -> float:
    """The parameter count a tag names (``llama3.1:8b`` -> 8.0), or 0 when it names none."""
    found = re.search(r":(\d+(?:\.\d+)?)b\b", name)
    return float(found.group(1)) if found else 0.0


def installed_chat_model(listed: list[str]) -> str | None:
    """The Ollama chat model to propose among the installed ``listed`` models; None when only embedders are.

    The largest model of a known family wins, then the family order: a 3B model often fails the structured
    replies a pack draft needs where an 8B one of a lower-ranked family succeeds.
    """
    chat = [name for name in listed if _family(name) not in OLLAMA_EMBEDDING_FAMILIES]
    known = [name for name in chat if _family(name) in OLLAMA_CHAT_FAMILIES]
    if known:
        return min(known, key=lambda name: (-_billions(name), OLLAMA_CHAT_FAMILIES.index(_family(name))))
    return chat[0] if chat else None


def installed_embedding_model(listed: list[str]) -> str | None:
    """The proposed Ollama embedding model when the server has it installed."""
    proposed = _EMBEDDING["ollama"]
    return next((name for name in listed if _family(name) == proposed), None)


def chat_models(kind: str) -> dict[str, str]:
    """The proposed model of each chat tier for a provider of ``kind``; empty when none can be proposed."""
    return dict(_CHAT.get(kind, {}))


def embedding_model(kind: str) -> str | None:
    return _EMBEDDING.get(kind)


def fixed_dimensions(model: str) -> int | None:
    """The only vector size ``model`` returns, or None when it returns the size it is asked for."""
    return _FIXED_DIMENSIONS.get(model) or _FIXED_DIMENSIONS.get(model.removesuffix(":latest"))


def proposed_dimensions(model: str) -> int | None:
    """The vector size proposed for an embedding model of ``embedding_model``."""
    return _PROPOSED_DIMENSIONS.get(model)
