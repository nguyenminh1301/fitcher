"""The LiteLLM chat client and the fake used by node tests, without network access."""

import json

from fake_llm import FakeLLMClient
import httpx
from pydantic import BaseModel
import pytest

from app.llm.client import LiteLLMClient, LLMError


class Answer(BaseModel):
    word: str
    count: int


def client(handler) -> LiteLLMClient:
    return LiteLLMClient("http://litellm:4000/", "sk-test", http=httpx.Client(transport=httpx.MockTransport(handler)))


def reply(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def test_structured_sends_the_alias_and_json_schema_then_validates():
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append({"url": str(request.url), "auth": request.headers["Authorization"], **json.loads(request.content)})
        return reply('{"word": "ready", "count": 2}')

    answer = client(handler).structured("fast", "Say ready twice", Answer)

    assert answer == Answer(word="ready", count=2)
    request = sent[0]
    assert request["url"] == "http://litellm:4000/v1/chat/completions"
    assert request["auth"] == "Bearer sk-test"
    assert request["model"] == "fast"
    assert request["messages"] == [{"role": "user", "content": "Say ready twice"}]
    assert request["response_format"]["json_schema"]["name"] == "Answer"
    assert request["response_format"]["json_schema"]["schema"]["required"] == ["word", "count"]


def test_text_returns_the_reply_without_a_response_format():
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return reply("SELECT 1")

    assert client(handler).text("sql-gen", "Write SQL") == "SELECT 1"
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
        client(lambda request: response).structured("fast", "hi", Answer)


def test_schema_mismatch_does_not_echo_the_reply():
    with pytest.raises(LLMError) as raised:
        client(lambda request: reply('{"word": "secret-value", "count": "many"}')).structured("fast", "hi", Answer)

    assert "secret-value" not in str(raised.value) and "many" not in str(raised.value)


def test_missing_gateway_settings_are_rejected():
    with pytest.raises(LLMError, match="must be set"):
        LiteLLMClient("", "sk-test")


def test_fake_client_records_calls_and_checks_aliases():
    fake = FakeLLMClient([{"word": "a", "count": 1}, "plain"])

    assert fake.structured("fast", "p1", Answer) == Answer(word="a", count=1)
    assert fake.text("sql-gen-hard", "p2") == "plain"
    assert [(call.method, call.alias, call.prompt) for call in fake.calls] == [
        ("structured", "fast", "p1"), ("text", "sql-gen-hard", "p2"),
    ]
    with pytest.raises(ValueError):
        fake.text("gpt-5.4", "p3")
