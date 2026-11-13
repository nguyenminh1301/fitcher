"""Listing a provider's models over each provider's own API, with a mock transport instead of the network."""

import httpx
import pytest

from app.llm.provider_models import list_models, ModelListError
from app.llm.providers import Provider

KEY = "sk-test-list-key-2468"


def provider(kind: str, base_url: str | None = None, key: bool = True) -> Provider:
    return Provider(id=kind, name=kind, kind=kind, base_url=base_url, key_set=key, key_last4="2468" if key else None)


def client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def recorder(body: dict, sent: list[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json=body)
    return handler


def test_openai_lists_its_models_with_a_bearer_key():
    sent: list[httpx.Request] = []
    body = {"data": [{"id": "gpt-5.4"}, {"id": "gpt-5.4-mini"}, {"id": "text-embedding-3-large"}]}

    models = list_models(provider("openai"), KEY, client(recorder(body, sent)))

    assert models == ["gpt-5.4", "gpt-5.4-mini", "text-embedding-3-large"]
    assert str(sent[0].url) == "https://api.openai.com/v1/models"
    assert sent[0].headers["Authorization"] == f"Bearer {KEY}"


def test_anthropic_sends_its_key_and_version_headers():
    sent: list[httpx.Request] = []

    models = list_models(provider("anthropic"), KEY, client(recorder({"data": [{"id": "claude-haiku-5-5"}]}, sent)))

    assert models == ["claude-haiku-5-5"]
    assert str(sent[0].url).startswith("https://api.anthropic.com/v1/models")
    assert sent[0].headers["x-api-key"] == KEY and sent[0].headers["anthropic-version"]


def test_gemini_sends_its_key_in_a_header_and_strips_the_models_prefix():
    sent: list[httpx.Request] = []
    body = {"models": [{"name": "models/gemini-2.5-flash"}, {"name": "models/gemini-embedding-001"}]}

    models = list_models(provider("gemini"), KEY, client(recorder(body, sent)))

    assert models == ["gemini-2.5-flash", "gemini-embedding-001"]
    assert sent[0].headers["x-goog-api-key"] == KEY
    assert KEY not in str(sent[0].url)


def test_ollama_lists_its_local_tags():
    sent: list[httpx.Request] = []
    body = {"models": [{"name": "qwen2.5-coder:7b"}, {"name": "nomic-embed-text:latest"}]}

    models = list_models(provider("ollama", "http://host.docker.internal:11434", key=False), None, client(recorder(body, sent)))

    assert models == ["nomic-embed-text:latest", "qwen2.5-coder:7b"]
    assert str(sent[0].url) == "http://host.docker.internal:11434/api/tags"


def test_an_openai_compatible_endpoint_is_listed_under_its_base_url_with_or_without_a_key():
    sent: list[httpx.Request] = []
    lab = provider("openai_compatible", "http://host.docker.internal:1234/v1", key=False)

    assert list_models(lab, None, client(recorder({"data": [{"id": "local"}]}, sent))) == ["local"]
    assert str(sent[0].url) == "http://host.docker.internal:1234/v1/models"
    assert "Authorization" not in sent[0].headers


@pytest.mark.parametrize(("response", "message"), [
    (httpx.Response(401, text=f"invalid key {KEY}"), "HTTP 401"),
    (httpx.Response(200, text="<html>not json</html>"), "unknown shape"),
    (httpx.Response(200, json={"data": "nope"}), "unknown shape"),
])
def test_a_failed_listing_raises_without_echoing_the_reply(response, message):
    with pytest.raises(ModelListError, match=message) as raised:
        list_models(provider("openai"), KEY, client(lambda request: response))
    assert KEY not in str(raised.value)


def test_an_unreachable_server_names_the_error_type_only():
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"refused {request.url}")

    lab = provider("ollama", "http://10.0.0.7:11434", key=False)
    with pytest.raises(ModelListError, match="ConnectError") as raised:
        list_models(lab, None, client(refuse))
    assert "10.0.0.7" not in str(raised.value)
