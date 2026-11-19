"""The model a provider check asks: the smallest chat model in what the provider lists."""

import pytest

from app.llm.defaults import probe_model

GROQ = ["allam-2-7b", "canopylabs/orpheus-v1-english", "meta-llama/llama-prompt-guard-2-86m", "openai/gpt-oss-120b",
        "openai/gpt-oss-20b", "openai/gpt-oss-safeguard-20b", "qwen/qwen3.8-27b", "whisper-large-v3"]
ZAI = ["glm-4.5", "glm-4.5-air", "glm-5", "glm-5.3", "glm-5.3-flash", "glm-5.3-flashx", "glm-5.3-flashx-legal"]
GEMINI = ["aqa", "gemini-2.5-flash-preview-tts", "gemini-2.5-pro", "gemini-3.1-flash-image", "gemini-3.1-flash-lite-preview",
          "gemini-3.8-flash", "gemini-3.8-live", "gemini-embedding-001", "gemini-flash-lite-latest", "gemini-robotics-er-2-preview"]
OPENROUTER = ["anthropic/claude-opus-5.5", "cohere/north-mini-code:free", "inclusionai/ling-3.2-flash:free",
              "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free", "nvidia/nemotron-3-ultra-550b-a55b:free",
              "openai/gpt-5.4-nano", "z-ai/glm-5.3-flash"]
OPENAI = ["gpt-4o-mini-transcribe", "gpt-5.4", "gpt-5.4-mini", "gpt-5.4-nano", "gpt-5.5", "gpt-realtime-mini",
          "text-embedding-3-large", "tts-1"]


@pytest.mark.parametrize(("kind", "listed", "expected"), [
    ("openai_compatible", GROQ, "openai/gpt-oss-20b"),
    ("gemini", GEMINI, "gemini-flash-lite-latest"),
    ("openai_compatible", OPENROUTER, "inclusionai/ling-3.2-flash:free"),
    ("openai", OPENAI, "gpt-5.4-nano"),
])
def test_the_check_model_is_small_fast_and_able_to_chat(kind, listed, expected):
    assert probe_model(kind, listed) == expected


def test_a_list_without_a_size_word_falls_back_to_the_proposed_or_first_chat_model():
    assert probe_model("openai", ["gpt-5.4-mini-tts", "gpt-5.4"]) == "gpt-5.4"
    assert probe_model("openai_compatible", ["whisper-large-v3", "lab-model"]) == "lab-model"


def test_a_list_with_no_chat_model_has_no_check_model():
    assert probe_model("openai_compatible", ["whisper-large-v3", "text-embedding-3-large"]) is None


def test_a_service_that_hides_its_free_model_is_checked_with_that_model():
    # Z.ai lists only paid models; a free account is refused by them with "insufficient balance".
    assert probe_model("openai_compatible", ZAI, "https://api.z.ai/api/paas/v4") == "glm-4.5-flash"
    assert probe_model("openai_compatible", ZAI) == "glm-5.3-flash"
