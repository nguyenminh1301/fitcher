"""The models a provider offers, read from the provider's own listing endpoint.

This is the only provider request outside the gateway: it lists model names
and sends no prompt, so it needs no screening. An error names the HTTP status
or the error type only, never the reply or the address, because either can
quote the key or the network layout.
"""

from urllib.parse import urlsplit

import httpx

from app.llm.providers import Provider

TIMEOUT_SECONDS = 15
ANTHROPIC_VERSION = "2023-06-01"
# The statuses a provider answers a wrong key with; Gemini answers 400 for a key it does not know.
REFUSED_KEY = frozenset({400, 401, 403})


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


def fetch_listing(provider: Provider, api_key: str | None, http: httpx.Client | None = None) -> dict:
    """The provider's model listing as it sent it, with whatever details it gives per model."""
    url, headers = _request(provider, api_key)
    http = http or httpx.Client(timeout=TIMEOUT_SECONDS)
    try:
        response = http.get(url, headers=headers)
    except httpx.HTTPError as error:
        raise ModelListError(f"{provider.name} did not answer: {type(error).__name__}") from None
    if response.status_code in REFUSED_KEY:
        raise ModelListError(f"{provider.name} refused the key (HTTP {response.status_code}); check that the key "
                             f"was created for {provider.name}")
    if response.status_code != 200:
        raise ModelListError(f"{provider.name} returned HTTP {response.status_code} for its model list")
    try:
        body = response.json()
    except ValueError:
        raise ModelListError(f"{provider.name} listed its models in an unknown shape") from None
    if not isinstance(body, dict):
        raise ModelListError(f"{provider.name} listed its models in an unknown shape")
    return body


def listing_items(provider: Provider, body: dict) -> list[tuple[str, dict]]:
    """Each listed model's name with the details the provider gave for it."""
    try:
        if provider.kind == "gemini":
            return [(str(item["name"]).removeprefix("models/"), item) for item in body["models"]]
        if provider.kind == "ollama":
            return [(str(item["name"]), item) for item in body["models"]]
        return [(str(item["id"]), item) for item in body["data"]]
    except (KeyError, TypeError, AttributeError):
        raise ModelListError(f"{provider.name} listed its models in an unknown shape") from None


def list_models(provider: Provider, api_key: str | None, http: httpx.Client | None = None) -> list[str]:
    """The provider's model names, sorted."""
    return sorted({name for name, _ in listing_items(provider, fetch_listing(provider, api_key, http))})


# Services whose model list answers without a key, with the address that answers only to a valid key.
# OpenRouter lists its models to anyone, so a wrong key would pass a listing; its key endpoint costs no tokens.
_KEY_ENDPOINTS = {"openrouter.ai": "/key"}


def _key_endpoint(provider: Provider) -> str | None:
    if provider.kind != "openai_compatible" or not provider.base_url:
        return None
    host = urlsplit(provider.base_url).hostname or ""
    path = next((path for domain, path in _KEY_ENDPOINTS.items() if host == domain or host.endswith(f".{domain}")), None)
    return f"{provider.base_url}{path}" if path else None


def checked_models(provider: Provider, api_key: str | None, http: httpx.Client | None = None) -> list[str]:
    """The provider's model names, read only after the provider accepted ``api_key``; sends no prompt.

    A refused key raises ``ModelListError`` with the HTTP status, so a key is never stored or kept as working
    when the provider would refuse every question with it.
    """
    http = http or httpx.Client(timeout=TIMEOUT_SECONDS)
    endpoint = _key_endpoint(provider) if api_key else None
    if endpoint:
        try:
            response = http.get(endpoint, headers={"Authorization": f"Bearer {api_key}"})
        except httpx.HTTPError as error:
            raise ModelListError(f"{provider.name} did not answer: {type(error).__name__}") from None
        if response.status_code != 200:
            raise ModelListError(f"{provider.name} refused the key (HTTP {response.status_code})")
    return list_models(provider, api_key, http)
