import json

import httpx
from openai import OpenAI
import pytest

from scripts import check_openai


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    monkeypatch.setattr(check_openai, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_SMOKE_MODEL", "test-model")


def install_transport(monkeypatch, handler):
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret-never-print")
    monkeypatch.setattr(
        check_openai,
        "OpenAI",
        lambda **kwargs: OpenAI(
            **kwargs,
            base_url="https://openai.invalid/v1",
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        ),
    )


def test_missing_key_fails_with_configuration_guidance(capsys):
    assert check_openai.main() == 1
    assert "OPENAI_API_KEY" in capsys.readouterr().err


def test_success_sends_bounded_responses_request(monkeypatch, capsys):
    def respond(request):
        assert request.url.path == "/v1/responses"
        body = json.loads(request.content)
        assert body["model"] == "test-model"
        assert body["store"] is False
        assert body["max_output_tokens"] == 128
        return httpx.Response(200, json={
            "id": "resp_test", "object": "response", "created_at": 0,
            "status": "completed", "error": None, "incomplete_details": None,
            "output": [{
                "id": "msg_test", "type": "message", "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": "OK", "annotations": []}],
            }],
        })

    install_transport(monkeypatch, respond)
    assert check_openai.main() == 0
    output = capsys.readouterr()
    assert "succeeded" in output.out
    assert "test-secret" not in output.out + output.err


def test_api_failure_has_safe_diagnostics(monkeypatch, capsys):
    install_transport(monkeypatch, lambda request: httpx.Response(401, json={
        "error": {"message": "Bad key: test-secret-never-print", "type": "invalid_request_error"},
    }))
    assert check_openai.main() == 1
    output = capsys.readouterr()
    assert "401" in output.err
    assert "test-secret" not in output.out + output.err


@pytest.mark.parametrize("status", ["completed", "incomplete"])
def test_empty_or_incomplete_response_is_not_success(monkeypatch, capsys, status):
    install_transport(monkeypatch, lambda request: httpx.Response(200, json={
        "id": "resp_empty", "object": "response", "created_at": 0,
        "status": status, "output": [], "error": None,
        "incomplete_details": None,
    }))
    assert check_openai.main() == 1
    assert "usable text" in capsys.readouterr().err
