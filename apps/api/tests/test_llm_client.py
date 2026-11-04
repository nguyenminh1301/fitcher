"""The LiteLLM chat client and the fake used by node tests, without network access."""

import json

from fake_llm import FakeLLMClient
import httpx
from pydantic import BaseModel
import pytest

from app.llm.client import GatewayBlocked, LiteLLMClient, LLMError, Prompt


class Answer(BaseModel):
    word: str
    count: int


PROMPT = Prompt(system="Reply in JSON.", user="Say ready twice")


def client(handler) -> LiteLLMClient:
    return LiteLLMClient("http://litellm:4000/", "sk-test", http=httpx.Client(transport=httpx.MockTransport(handler)))


def reply(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def test_structured_sends_the_alias_and_json_schema_then_validates():
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append({"url": str(request.url), "auth": request.headers["Authorization"], **json.loads(request.content)})
        return reply('{"word": "ready", "count": 2}')

    answer = client(handler).structured("fast", PROMPT, Answer)

    assert answer == Answer(word="ready", count=2)
    request = sent[0]
    assert request["url"] == "http://litellm:4000/v1/chat/completions"
    assert request["auth"] == "Bearer sk-test"
    assert request["model"] == "fast"
    assert request["messages"] == [
        {"role": "system", "content": "Reply in JSON."}, {"role": "user", "content": "Say ready twice"},
    ]
    assert request["response_format"]["json_schema"]["name"] == "Answer"
    assert request["response_format"]["json_schema"]["schema"]["required"] == ["word", "count"]


def test_text_returns_the_reply_without_a_response_format():
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return reply("SELECT 1")

    assert client(handler).text("sql-gen", PROMPT) == "SELECT 1"
    assert "response_format" not in sent[0]


@pytest.mark.parametrize("alias", ["gpt-5.4", "openai/gpt-5.4-mini", "embed", ""])
def test_only_chat_alias_names_are_accepted(alias):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request may be sent")

    with pytest.raises(ValueError, match="unknown LLM alias"):
        client(handler).text(alias, "hi")


@pytest.mark.parametrize(("response", "message"), [
    (httpx.Response(500, json={"error": "boom"}), "returned HTTP 500"),
    (reply("   "), "empty reply"),
    (reply("not json"), "does not match Answer"),
    (reply('{"word": "x"}'), "does not match Answer"),
    (httpx.Response(200, content=b"<html>"), "not JSON"),
    (httpx.Response(200, json=["not", "an", "object"]), "empty reply"),
    (httpx.Response(200, json={"choices": []}), "empty reply"),
    (httpx.Response(200, json={"choices": [{"message": "text"}]}), "empty reply"),
    (httpx.Response(200, json={"choices": [{"message": {"content": 42}}]}), "malformed reply"),
])
def test_failures_raise_llm_error(response, message):
    with pytest.raises(LLMError, match=message):
        client(lambda request: response).structured("fast", PROMPT, Answer)


def test_schema_mismatch_does_not_echo_the_reply():
    with pytest.raises(LLMError) as raised:
        client(lambda request: reply('{"word": "secret-value", "count": "many"}')).structured("fast", PROMPT, Answer)

    assert "secret-value" not in str(raised.value) and "many" not in str(raised.value)
    assert raised.value.__cause__ is None and raised.value.__context__ is None


def test_missing_gateway_settings_are_rejected():
    with pytest.raises(LLMError, match="must be set"):
        LiteLLMClient("", "sk-test")


def test_fake_client_records_calls_and_checks_aliases():
    fake = FakeLLMClient([{"word": "a", "count": 1}, "plain"])

    assert fake.structured("fast", PROMPT, Answer) == Answer(word="a", count=1)
    assert fake.text("sql-gen-hard", PROMPT) == "plain"
    assert [(call.method, call.alias, call.prompt) for call in fake.calls] == [
        ("structured", "fast", PROMPT.text), ("text", "sql-gen-hard", PROMPT.text),
    ]
    assert (fake.calls[0].system, fake.calls[0].user) == ("Reply in JSON.", "Say ready twice")
    with pytest.raises(ValueError):
        fake.text("gpt-5.4", PROMPT)


def _sent_payload(llm_factory) -> dict:
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return reply("SELECT 1")

    llm_factory(handler).text("sql-gen", PROMPT)
    return sent[0]


def test_temperature_is_sent_when_set():
    def with_temperature(handler) -> LiteLLMClient:
        transport = httpx.Client(transport=httpx.MockTransport(handler))
        return LiteLLMClient("http://litellm:4000/", "sk-test", http=transport, temperature=0)

    assert _sent_payload(with_temperature)["temperature"] == 0


def test_temperature_is_omitted_by_default():
    assert "temperature" not in _sent_payload(client)


def test_a_screening_guardrail_rejection_raises_gateway_blocked():
    rejected = httpx.Response(400, json={"error": {"message": "screening_guard: the request carries no screening metadata"}})

    with pytest.raises(GatewayBlocked):
        client(lambda request: rejected).text("fast", PROMPT)


def test_another_client_error_stays_an_llm_error():
    with pytest.raises(LLMError, match="returned HTTP 400"):
        client(lambda request: httpx.Response(400, json={"error": "bad request"})).text("fast", PROMPT)
