"""The models a provider offers, read from the provider's own listing endpoint.

This is the only provider request outside the gateway: it lists model names
and sends no prompt, so it needs no screening. An error names the HTTP status
or the error type only, never the reply or the address, because either can
quote the key or the network layout.
"""

import httpx

from app.llm.providers import Provider

TIMEOUT_SECONDS = 15
ANTHROPIC_VERSION = "2023-06-01"


class ModelListError(RuntimeError):
    """The provider did not list its models."""


def _request(provider: Provider, api_key: str | None) -> tuple[str, dict[str, str]]:
    if provider.kind == "openai":
        return "https://api.openai.com/v1/models", {"Authorization": f"Bearer {api_key}"}
    if provider.kind == "anthropic":
        return "https://api.anthropic.com/v1/models?limit=1000", {
            "x-api-key": api_key or "", "anthropic-version": ANTHROPIC_VERSION,
        }
    if provider.kind == "gemini":
        return "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000", {"x-goog-api-key": api_key or ""}
    if provider.kind == "ollama":
        return f"{provider.base_url}/api/tags", {}
    return f"{provider.base_url}/models", {"Authorization": f"Bearer {api_key}"} if api_key else {}


def _names(kind: str, body: dict) -> list[str]:
    if kind == "gemini":
        return [str(item["name"]).removeprefix("models/") for item in body["models"]]
    if kind == "ollama":
        return [str(item["name"]) for item in body["models"]]
    return [str(item["id"]) for item in body["data"]]


def list_models(provider: Provider, api_key: str | None, http: httpx.Client | None = None) -> list[str]:
    """The provider's model names, sorted."""
    url, headers = _request(provider, api_key)
    http = http or httpx.Client(timeout=TIMEOUT_SECONDS)
    try:
        response = http.get(url, headers=headers)
    except httpx.HTTPError as error:
        raise ModelListError(f"{provider.name} did not answer: {type(error).__name__}") from None
    if response.status_code != 200:
        raise ModelListError(f"{provider.name} returned HTTP {response.status_code} for its model list")
    try:
        return sorted(set(_names(provider.kind, response.json())))
    except (ValueError, KeyError, TypeError, AttributeError):
        raise ModelListError(f"{provider.name} listed its models in an unknown shape") from None
