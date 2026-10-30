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


def reply(content):
    body = {"choices": [{"message": {"role": "assistant", "content": content}}]}
    return FakeResponse(json.dumps(body).encode())


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("LITELLM_BASE_URL", "http://litellm:4000")
    monkeypatch.setenv("LITELLM_MASTER_KEY", SECRET)


def test_calls_fast_alias_through_gateway(env, monkeypatch, capsys):
    sent = {}

    def fake_urlopen(request, timeout):
        sent["url"] = request.full_url
        sent["auth"] = request.get_header("Authorization")
        sent["body"] = json.loads(request.data)
        return reply("private reply text")

    monkeypatch.setattr(smoke_llm.urllib.request, "urlopen", fake_urlopen)

    assert smoke_llm.main() == 0
    assert sent["url"] == "http://litellm:4000/v1/chat/completions"
    assert sent["auth"] == f"Bearer {SECRET}"
    assert sent["body"]["model"] == "fast"
    out = capsys.readouterr().out
    assert "18 characters" in out
    assert "private reply text" not in out


def test_empty_reply_fails(env, monkeypatch):
    monkeypatch.setattr(smoke_llm.urllib.request, "urlopen", lambda r, timeout: reply("  "))
    assert smoke_llm.main() == 1


def test_missing_settings_fail_without_request(monkeypatch):
    monkeypatch.delenv("LITELLM_BASE_URL", raising=False)
    monkeypatch.delenv("LITELLM_MASTER_KEY", raising=False)

    def fail(*args, **kwargs):
        raise AssertionError("no request expected")

    monkeypatch.setattr(smoke_llm.urllib.request, "urlopen", fail)
    assert smoke_llm.main() == 1


def test_gateway_error_reports_status_without_secret(env, monkeypatch, capsys):
    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, io.BytesIO(SECRET.encode()))

    monkeypatch.setattr(smoke_llm.urllib.request, "urlopen", fake_urlopen)

    assert smoke_llm.main() == 1
    captured = capsys.readouterr()
    assert "401" in captured.err
    assert SECRET not in captured.out + captured.err
