"""A chat tier's fallback chain and the rotation of a provider's keys, with a fake SDK; no request leaves the test."""

from collections.abc import Iterator

import litellm
import pytest

from app.llm.client import LLMError, Prompt
from app.llm.gateway import Gateway, Route
from app.llm.key_pool import COOLDOWN_SECONDS, KeyPool
from app.observability.tracing import trusted_pack_calls

PROMPT = Prompt(system="Reply.", user="Say ready")


def route(provider: str, model: str, key: str | None = None) -> Route:
    return Route(provider=provider, model=f"openai/{model}", api_key=f"secret-{key}" if key else None,
                 api_base="https://example.test/v1", key_id=key)


GROQ_A, GROQ_B = route("groq", "gpt-oss-120b", "a"), route("groq", "gpt-oss-120b", "b")
GEMINI = route("gemini", "gemini-2.5-flash", "g")
LOCAL = route("lab", "local-model")


class Chains:
    def __init__(self, chain: list[list[Route]]):
        self._chain = chain

    def chain(self, tier: str) -> list[list[Route]]:
        return self._chain

    def route(self, tier: str) -> Route:
        return self._chain[0][0]


def reply(content: str | None = "ready") -> litellm.ModelResponse:
    return litellm.ModelResponse(
        model="m", choices=[{"message": {"role": "assistant", "content": content}, "index": 0, "finish_reason": "stop"}],
        usage={"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
    )


def rate_limited(retry_after: str | None = None) -> litellm.RateLimitError:
    error = litellm.RateLimitError("limit reached for key secret-a", "groq", "gpt-oss-120b")
    if retry_after is not None:
        error.litellm_response_headers = {"retry-after": retry_after}
    return error


class Sdk:
    """Answers each call from a function of the route's key or model; records the calls."""

    def __init__(self, answer):
        self.answer = answer
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        result = self.answer(kwargs)
        if isinstance(result, BaseException):
            raise result
        return result


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture(autouse=True)
def screened() -> Iterator[None]:
    with trusted_pack_calls():
        yield


def gateway(chain, sdk, pool=None, logs=None) -> Gateway:
    return Gateway(Chains(chain), completion=sdk, keys=pool or KeyPool(Clock()), call_log=logs.append if logs is not None else None)


def test_the_keys_of_a_provider_take_turns_from_call_to_call():
    sdk = Sdk(lambda call: reply())
    chat = gateway([[GROQ_A, GROQ_B]], sdk)

    for _ in range(3):
        chat.text("fast", PROMPT)

    assert [call["api_key"] for call in sdk.calls] == ["secret-a", "secret-b", "secret-a"]
    # With a chain, the next key or model is the retry.
    assert {call["num_retries"] for call in sdk.calls} == {0}


def test_a_rate_limited_key_rests_while_the_next_key_answers():
    clock = Clock()
    pool = KeyPool(clock)
    sdk = Sdk(lambda call: rate_limited() if call["api_key"] == "secret-a" else reply())
    chat = gateway([[GROQ_A, GROQ_B]], sdk, pool)

    assert chat.text("fast", PROMPT) == "ready"
    assert [call["api_key"] for call in sdk.calls] == ["secret-a", "secret-b"]
    chat.text("fast", PROMPT)
    chat.text("fast", PROMPT)
    assert [call["api_key"] for call in sdk.calls[2:]] == ["secret-b", "secret-b"]
    clock.now += COOLDOWN_SECONDS + 1
    chat.text("fast", PROMPT)
    chat.text("fast", PROMPT)
    assert "secret-a" in [call["api_key"] for call in sdk.calls[4:]]


def test_a_rate_limited_key_rests_as_long_as_the_provider_asks():
    clock = Clock()
    pool = KeyPool(clock)
    sdk = Sdk(lambda call: rate_limited("120") if call["api_key"] == "secret-a" else reply())
    chat = gateway([[GROQ_A, GROQ_B]], sdk, pool)
    chat.text("fast", PROMPT)

    clock.now += COOLDOWN_SECONDS + 1
    assert pool.order([GROQ_A, GROQ_B]) == [GROQ_B]
    clock.now += 60
    assert GROQ_A in pool.order([GROQ_A, GROQ_B])


def test_a_refused_key_is_not_tried_again():
    pool = KeyPool(Clock())
    refused = litellm.AuthenticationError("invalid key secret-a", "groq", "gpt-oss-120b")
    sdk = Sdk(lambda call: refused if call["api_key"] == "secret-a" else reply())
    chat = gateway([[GROQ_A, GROQ_B]], sdk, pool)

    for _ in range(3):
        chat.text("fast", PROMPT)

    assert [call["api_key"] for call in sdk.calls] == ["secret-a", "secret-b", "secret-b", "secret-b"]


def test_the_next_model_answers_when_every_key_of_the_first_is_limited_and_the_rows_link_them():
    logs: list = []
    sdk = Sdk(lambda call: rate_limited() if "gpt-oss" in call["model"] else reply("from gemini"))
    chat = gateway([[GROQ_A, GROQ_B], [GEMINI]], sdk, logs=logs)

    assert chat.text("fast", PROMPT) == "from gemini"
    assert [(row.provider, row.status) for row in logs] == [("groq", "failure"), ("groq", "failure"), ("gemini", "success")]
    assert all(row.call_id for row in logs)
    assert [row.fallback_of for row in logs] == ["", logs[0].call_id, logs[1].call_id]


@pytest.mark.parametrize("error", [
    litellm.Timeout("slow", "openai/gpt-oss-120b", "groq"),
    litellm.APIConnectionError("down", "groq", "gpt-oss-120b"),
    litellm.ServiceUnavailableError("busy", "groq", "gpt-oss-120b"),
    litellm.NotFoundError("no such model", "groq", "gpt-oss-120b"),
])
def test_an_outage_moves_to_the_next_model_without_trying_the_other_keys(error):
    sdk = Sdk(lambda call: error if "gpt-oss" in call["model"] else reply("fallback"))

    assert gateway([[GROQ_A, GROQ_B], [LOCAL]], sdk).text("fast", PROMPT) == "fallback"
    assert len(sdk.calls) == 2


def test_an_empty_reply_moves_to_the_next_model_after_one_more_try():
    sdk = Sdk(lambda call: reply(None) if "gpt-oss" in call["model"] else reply("fallback"))

    assert gateway([[GROQ_A], [LOCAL]], sdk).text("fast", PROMPT) == "fallback"
    assert len(sdk.calls) == 3


def test_an_invalid_request_stops_the_chain():
    sdk = Sdk(lambda call: litellm.BadRequestError("bad schema", "gpt-oss-120b", "groq"))

    with pytest.raises(LLMError, match="BadRequestError") as raised:
        gateway([[GROQ_A], [LOCAL]], sdk).text("fast", PROMPT)

    assert len(sdk.calls) == 1
    assert raised.value.attempts == (("openai/gpt-oss-120b", "BadRequestError"),)


def test_an_exhausted_chain_lists_every_attempt_without_the_providers_messages():
    sdk = Sdk(lambda call: rate_limited() if "gpt-oss" in call["model"] else litellm.Timeout("slow secret-g", "m", "p"))

    with pytest.raises(LLMError) as raised:
        gateway([[GROQ_A, GROQ_B], [GEMINI]], sdk).text("fast", PROMPT)

    message = str(raised.value)
    assert message.startswith("every model of the fast tier failed: openai/gpt-oss-120b: RateLimitError")
    assert "openai/gemini-2.5-flash: Timeout" in message
    assert "secret" not in message
    assert [model for model, _ in raised.value.attempts] == [
        "openai/gpt-oss-120b", "openai/gpt-oss-120b", "openai/gemini-2.5-flash"]


def test_a_model_whose_keys_all_rest_is_skipped_without_a_call():
    clock = Clock()
    pool = KeyPool(clock)
    pool.rest(GROQ_A, None)
    pool.rest(GROQ_B, None)
    sdk = Sdk(lambda call: reply("fallback"))

    assert gateway([[GROQ_A, GROQ_B], [LOCAL]], sdk, pool).text("fast", PROMPT) == "fallback"
    assert [call["model"] for call in sdk.calls] == ["openai/local-model"]


def test_a_single_route_keeps_the_sdk_retries_and_the_one_model_message():
    sdk = Sdk(lambda call: rate_limited())

    with pytest.raises(LLMError, match=r"^request to model openai/gpt-oss-120b failed: RateLimitError"):
        gateway([[GROQ_A]], sdk).text("fast", PROMPT)

    assert sdk.calls[0]["num_retries"] == 2


def test_a_refused_key_reported_as_a_bad_request_is_still_a_refused_key():
    # Groq answers an invalid key with HTTP 401 that the SDK raises as BadRequestError.
    refused = litellm.BadRequestError("Invalid API Key", "gpt-oss-120b", "groq")
    refused.status_code = 401
    logs: list = []
    sdk = Sdk(lambda call: refused if call["api_key"] == "secret-a" else reply())

    assert gateway([[GROQ_A, GROQ_B]], sdk, logs=logs).text("fast", PROMPT) == "ready"
    assert [row.error for row in logs] == ["AuthenticationError", ""]
