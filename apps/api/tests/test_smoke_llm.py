"""The billable smoke job, with the gateway faked: one structured or embedding call per catalog alias."""

import io
import json
import urllib.error

import pytest

from jobs import smoke_llm

SECRET = "sk-test-master-key"


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def response(body: dict) -> FakeResponse:
    return FakeResponse(json.dumps(body).encode())


def chat(content: str) -> FakeResponse:
    return response({"choices": [{"message": {"role": "assistant", "content": content}}]})


class Gateway:
    """Answers /v1/models with ``aliases`` and each call from ``replies`` by alias."""

    def __init__(self, aliases: list[str], replies: dict | None = None):
        self.aliases = aliases
        self.replies = replies or {}
        self.sent: list[tuple[str, dict | None, str]] = []

    def __call__(self, request, timeout):
        body = json.loads(request.data) if request.data else None
        self.sent.append((request.full_url, body, request.get_header("Authorization")))
        if request.full_url.endswith("/v1/models"):
            return response({"data": [{"id": alias} for alias in self.aliases]})
        reply = self.replies.get(body["model"])
        if isinstance(reply, Exception):
            raise reply
        if reply is not None:
            return reply
        if request.full_url.endswith("/v1/embeddings"):
            return response({"data": [{"index": 0, "embedding": [0.1, 0.2]}]})
        return chat('{"word": "ready", "count": 2}')


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("LITELLM_BASE_URL", "http://litellm:4000")
    monkeypatch.setenv("LITELLM_MASTER_KEY", SECRET)


def test_every_loaded_alias_gets_one_structured_or_embedding_call(env, monkeypatch, capsys):
    gateway = Gateway(["openai-embed", "openai-small", "anthropic-small"])
    monkeypatch.setattr(smoke_llm.urllib.request, "urlopen", gateway)

    assert smoke_llm.main([]) == 0

    calls = [(url.rsplit("/v1", 1)[1], body["model"]) for url, body, _ in gateway.sent if body]
    assert calls == [("/chat/completions", "anthropic-small"), ("/embeddings", "openai-embed"), ("/chat/completions", "openai-small")]
    chat_body = next(body for _, body, _ in gateway.sent if body and "messages" in body)
    assert chat_body["response_format"]["type"] == "json_schema"
    assert chat_body["metadata"] == {"screening": "trusted_pack"}
    assert all(auth == f"Bearer {SECRET}" for _, _, auth in gateway.sent)
    assert capsys.readouterr().out.splitlines() == ["anthropic-small: ok", "openai-embed: ok", "openai-small: ok"]


def test_an_alias_without_structured_output_fails_without_printing_the_reply(env, monkeypatch, capsys):
    gateway = Gateway(["gemini-small", "openai-small"], {"gemini-small": chat("private prose reply")})
    monkeypatch.setattr(smoke_llm.urllib.request, "urlopen", gateway)

    assert smoke_llm.main([]) == 1
    captured = capsys.readouterr()
    assert "gemini-small: FAIL (the reply is not JSON)" in captured.err
    assert "openai-small: ok" in captured.out
    assert "private prose reply" not in captured.out + captured.err


@pytest.mark.parametrize("content", ['{"word": "ready", "count": true}', '{"word": "ready", "count": 2, "extra": 1}', '{"word": 1, "count": 2}'])
def test_a_reply_outside_the_schema_fails(env, monkeypatch, capsys, content):
    monkeypatch.setattr(smoke_llm.urllib.request, "urlopen", Gateway(["openai-small"], {"openai-small": chat(content)}))

    assert smoke_llm.main([]) == 1
    assert "does not match the schema" in capsys.readouterr().err


def test_alias_limits_the_calls_and_an_unloaded_alias_is_refused(env, monkeypatch, capsys):
    gateway = Gateway(["openai-small", "openai-medium"])
    monkeypatch.setattr(smoke_llm.urllib.request, "urlopen", gateway)

    assert smoke_llm.main(["--alias", "openai-medium"]) == 0
    assert [body["model"] for _, body, _ in gateway.sent if body] == ["openai-medium"]
    assert smoke_llm.main(["--alias", "anthropic-small"]) == 1
    assert "has not loaded anthropic-small" in capsys.readouterr().err


def test_an_empty_catalog_fails(env, monkeypatch, capsys):
    monkeypatch.setattr(smoke_llm.urllib.request, "urlopen", Gateway([]))

    assert smoke_llm.main([]) == 1
    assert "loaded no alias" in capsys.readouterr().err


def test_missing_settings_fail_without_request(monkeypatch):
    monkeypatch.delenv("LITELLM_BASE_URL", raising=False)
    monkeypatch.delenv("LITELLM_MASTER_KEY", raising=False)

    def fail(*args, **kwargs):
        raise AssertionError("no request expected")

    monkeypatch.setattr(smoke_llm.urllib.request, "urlopen", fail)
    assert smoke_llm.main([]) == 1


def test_gateway_error_reports_status_without_secret(env, monkeypatch, capsys):
    error = urllib.error.HTTPError("http://litellm:4000/v1/chat/completions", 401, "Unauthorized", {}, io.BytesIO(SECRET.encode()))
    monkeypatch.setattr(smoke_llm.urllib.request, "urlopen", Gateway(["openai-small"], {"openai-small": error}))

    assert smoke_llm.main([]) == 1
    captured = capsys.readouterr()
    assert "openai-small: FAIL (HTTP 401)" in captured.err
    assert SECRET not in captured.out + captured.err
