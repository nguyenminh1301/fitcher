"""What each model of a provider is good for, what it costs and how fast it answered (DECISIONS §2).

A provider's own model listing gives names, and for some providers more: Gemini
names the methods a model supports and its input limit; OpenRouter and Groq give
per-token prices, the context length and the output modalities; OpenRouter also
lists the parameters a model accepts and Artificial Analysis' intelligence index.
Everything else comes from three places, in this order:

1. The provider's listing itself.
2. LiteLLM's bundled price table, looked up under the provider's own LiteLLM
   prefix (``groq/``, ``zai/``, ``gemini/`` ...), never under a name a generic
   OpenAI-compatible server happens to report.
3. OpenRouter's public model list (no key, no prompt), used only for the
   benchmark of a model another provider also serves under the same name.

``kind`` is ``chat`` for text generation, ``embedding`` for embedding models and
``other`` for speech, transcription, images, live audio, classifiers such as
Prompt Guard, and anything else a question cannot be sent to.

``free`` is ``free`` when calls cost nothing (a ``:free`` OpenRouter model, a
zero price, a model server on this computer) and ``free_tier`` when the provider
gives a rate-limited allowance without billing. The free tiers are a curated
table, not a guess, and are the published terms on 2026-11-19:

- Gemini (Google AI Studio): Flash and Flash-Lite models, Gemma models and the
  embedding models have a daily free allowance; Pro models are billed.
- Groq: every model is usable on the free plan within its rate limits.
- Z.ai: ``glm-4.5-flash``, ``glm-4.7-flash`` and ``glm-4.6v-flash`` are free of
  charge; newer ``-flash`` models such as ``glm-5.3-flash`` are billed and refuse
  an account without credit. Z.ai lists only its billed models, so its free
  ``glm-4.5-flash`` is added to its catalog.

``median_latency_ms`` is measured: the median latency of this instance's own
successful calls to the model over the last 7 days, from ``llm_calls``.

The catalog of a provider is kept for ``TTL_SECONDS``; the measured latency is
read fresh on each request.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
import re
import threading
import time
from typing import Literal
from urllib.parse import urlsplit

import httpx

from app.llm.provider_models import fetch_listing, listing_items, ModelListError, TIMEOUT_SECONDS
from app.llm.providers import Provider

Kind = Literal["chat", "embedding", "other"]
Free = Literal["none", "free", "free_tier"]
TTL_SECONDS = 6 * 3600
OPENROUTER_MODELS = "https://openrouter.ai/api/v1/models"
PER_MILLION = 1_000_000

# The hosted services reached through ``openai_compatible``, by host, with their LiteLLM price-table prefix.
SERVICES = {
    "openrouter.ai": "openrouter", "api.groq.com": "groq", "api.z.ai": "zai", "api.cerebras.ai": "cerebras",
    "api.deepseek.com": "deepseek", "api.mistral.ai": "mistral", "api.x.ai": "xai", "api.together.xyz": "together_ai",
    "api.fireworks.ai": "fireworks_ai",
}
# Models a question cannot be sent to, whatever the provider: speech, transcription, images, video, music,
# live audio, robotics, computer use, research agents and classifiers.
OTHER_NAME = re.compile(
    r"whisper|tts|orpheus|transcri|native-audio|speech|prompt-guard|safeguard|moderation|dall-e|image|imagen|veo|"
    r"lyria|banana|realtime|robotics|computer-use|deep-research|antigravity|^aqa$|(^|[-_.])live($|[-_.])",
)
EMBEDDING_NAME = re.compile(r"embed")
LITELLM_OTHER_MODES = frozenset({
    "audio_transcription", "audio_speech", "image_generation", "image_edit", "video_generation", "moderation",
    "rerank", "realtime", "ocr", "search",
})


@dataclass(frozen=True)
class CatalogModel:
    id: str
    provider_id: str
    kind: Kind
    free: Free
    # USD per million tokens; None when no source knows the price.
    input_price: float | None = None
    output_price: float | None = None
    context: int | None = None
    # Whether the model returns a reply that follows a JSON schema; None when no source says.
    structured_output: bool | None = None
    # Artificial Analysis' intelligence index, from OpenRouter's list.
    benchmark: float | None = None
    median_latency_ms: int | None = None


# Z.ai's free models (measured 2026-11-19 with a free account); Z.ai does not list the first one.
ZAI_FREE = frozenset({"glm-4.5-flash", "glm-4.7-flash", "glm-4.6v-flash"})
ZAI_UNLISTED = ("glm-4.5-flash",)


def service_of(provider: Provider) -> str:
    """``gemini``, ``openai``, ``anthropic``, ``ollama``, a known hosted service such as ``groq``, or ``custom``."""
    if provider.kind != "openai_compatible":
        return provider.kind
    host = urlsplit(provider.base_url or "").hostname or ""
    return next((name for suffix, name in SERVICES.items() if host == suffix or host.endswith("." + suffix)), "custom")


def _number(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _per_million(per_token: object) -> float | None:
    value = _number(per_token)
    return None if value is None else round(value * PER_MILLION, 6)


def _price_entry(service: str, model: str, table: Mapping[str, dict]) -> dict:
    """The LiteLLM price-table entry of the model under its provider's own prefix, or an empty one."""
    if service in ("openai", "anthropic"):
        names = [model, f"{service}/{model}"]
    elif service in ("gemini", *SERVICES.values()):
        names = [f"{service}/{model}"]
    else:
        return {}
    return next((table[name] for name in names if isinstance(table.get(name), dict)), {})


def _kind(service: str, model: str, item: dict, entry: dict) -> Kind:
    name = model.lower()
    if service == "gemini":
        methods = set(item.get("supportedGenerationMethods") or [])
        if "embedContent" in methods:
            return "embedding"
        return "chat" if "generateContent" in methods and not OTHER_NAME.search(name) else "other"
    if OTHER_NAME.search(name) or entry.get("mode") in LITELLM_OTHER_MODES:
        return "other"
    if EMBEDDING_NAME.search(name) or entry.get("mode") == "embedding":
        return "embedding"
    architecture = item.get("architecture") if isinstance(item.get("architecture"), dict) else {}
    outputs = architecture.get("output_modalities") or item.get("output_modalities")
    if isinstance(outputs, list) and outputs and "text" not in outputs:
        return "embedding" if "embeddings" in outputs else "other"
    return "chat"


def _free_tier(service: str, model: str, kind: Kind) -> bool:
    """The curated free tiers of the module docstring."""
    name = model.lower()
    if service == "gemini":
        return kind == "embedding" or (kind == "chat" and ("flash" in name or name.startswith("gemma")))
    if service == "groq":
        return kind != "other"
    return False


def free_call(model: str, api_base: str | None, call_type: str) -> bool:
    """Whether a call to the route's ``model`` (LiteLLM's ``prefix/name``) at ``api_base`` is on a free model or tier.

    A free tier (Gemini's flash and Gemma models, Groq) charges nothing on an account without billing, which is
    how a free key is used; with billing on, the provider's invoice is the exact amount.
    """
    host = urlsplit(api_base or "").hostname or ""
    service = next((name for suffix, name in SERVICES.items() if host == suffix or host.endswith("." + suffix)), None)
    prefix, _, name = model.partition("/")
    if service is None:
        service = "ollama" if prefix in ("ollama", "ollama_chat") else "custom" if api_base else prefix
    return _free(service, name or model, "embedding" if call_type == "embedding" else "chat", None, None) != "none"


def _free(service: str, model: str, kind: Kind, input_price: float | None, output_price: float | None) -> Free:
    if service == "ollama" or (service == "openrouter" and model.endswith(":free")):
        return "free"
    if service == "zai" and model in ZAI_FREE:
        return "free"
    if _free_tier(service, model, kind):
        return "free_tier"
    if input_price == 0 and output_price == 0 and kind == "chat":
        return "free"
    return "none"


def _structured(service: str, model: str, item: dict, entry: dict, kind: Kind) -> bool | None:
    if kind != "chat":
        return None
    parameters = item.get("supported_parameters")
    if isinstance(parameters, list):
        return "structured_outputs" in parameters or "response_format" in parameters
    if entry.get("supports_response_schema") is not None:
        return bool(entry["supports_response_schema"])
    if service == "gemini":
        # Gemini models take a response schema; Gemma models on the same API do not.
        return model.startswith("gemini-")
    if service == "zai" and model in ZAI_UNLISTED:
        return True  # answered the provider check's JSON schema on 2026-11-19
    return None


def _context(service: str, item: dict, entry: dict) -> int | None:
    for value in (item.get("inputTokenLimit"), item.get("context_length"), item.get("context_window"),
                  entry.get("max_input_tokens")):
        number = _number(value)
        if number:
            return int(number)
    return None


def _prices(item: dict, entry: dict) -> tuple[float | None, float | None]:
    pricing = item.get("pricing")
    if isinstance(pricing, dict) and ("prompt" in pricing or "completion" in pricing):
        return _per_million(pricing.get("prompt")), _per_million(pricing.get("completion"))
    return _per_million(entry.get("input_cost_per_token")), _per_million(entry.get("output_cost_per_token"))


def benchmark_index(openrouter_body: dict | None) -> dict[str, float]:
    """Artificial Analysis' intelligence index by OpenRouter id and by the id's last part, without ``:free``."""
    index: dict[str, float] = {}
    for item in (openrouter_body or {}).get("data") or []:
        if not isinstance(item, dict):
            continue
        benchmarks = item.get("benchmarks") if isinstance(item.get("benchmarks"), dict) else {}
        analysis = benchmarks.get("artificial_analysis") if isinstance(benchmarks.get("artificial_analysis"), dict) else {}
        value = _number(analysis.get("intelligence_index"))
        if value is None:
            continue
        name = str(item.get("id", "")).removesuffix(":free")
        index.setdefault(name, value)
        index.setdefault(name.rsplit("/", 1)[-1], value)
    return index


def _benchmark(model: str, item: dict, index: Mapping[str, float]) -> float | None:
    own = item.get("benchmarks") if isinstance(item.get("benchmarks"), dict) else {}
    analysis = own.get("artificial_analysis") if isinstance(own.get("artificial_analysis"), dict) else {}
    if _number(analysis.get("intelligence_index")) is not None:
        return _number(analysis["intelligence_index"])
    name = model.removesuffix(":free")
    return index.get(name, index.get(name.rsplit("/", 1)[-1]))


def build(provider: Provider, body: dict, *, price_table: Mapping[str, dict],
          benchmarks: Mapping[str, float]) -> list[CatalogModel]:
    """The catalog of the provider from its listing, sorted by kind then name; measured latency is added later."""
    service = service_of(provider)
    models = []
    listed = listing_items(provider, body)
    if service == "zai":
        known = {name for name, _ in listed}
        listed = [*listed, *((name, {}) for name in ZAI_UNLISTED if name not in known)]
    for model, item in listed:
        item = item if isinstance(item, dict) else {}
        entry = _price_entry(service, model, price_table)
        kind = _kind(service, model, item, entry)
        input_price, output_price = _prices(item, entry)
        models.append(CatalogModel(
            id=model, provider_id=provider.id, kind=kind,
            free=_free(service, model, kind, input_price, output_price),
            input_price=input_price, output_price=output_price, context=_context(service, item, entry),
            structured_output=_structured(service, model, item, entry, kind),
            benchmark=_benchmark(model, item, benchmarks) if kind == "chat" else None,
        ))
    order = {"chat": 0, "embedding": 1, "other": 2}
    return sorted({model.id: model for model in models}.values(), key=lambda model: (order[model.kind], model.id))


def with_latency(models: list[CatalogModel], latency: Mapping[str, int]) -> list[CatalogModel]:
    """The models with the median latency measured for them, keyed by model name."""
    return [replace(model, median_latency_ms=latency.get(model.id)) for model in models]


def _litellm_price_table() -> Mapping[str, dict]:
    from app.llm.gateway import litellm_module  # noqa: PLC0415 - shares the gateway's deferred import

    return litellm_module().model_cost


def _openrouter_models(http: httpx.Client | None = None) -> dict | None:
    """OpenRouter's public model list, or None when it cannot be read; it only adds benchmarks."""
    try:
        response = (http or httpx.Client(timeout=TIMEOUT_SECONDS)).get(OPENROUTER_MODELS)
        return response.json() if response.status_code == 200 else None
    except (httpx.HTTPError, ValueError):
        return None


class Catalog:
    """Each provider's catalog, kept ``TTL_SECONDS`` per provider, key and address."""

    def __init__(
        self, *, listing: Callable[[Provider, str | None], dict] = fetch_listing,
        reference: Callable[[], dict | None] = _openrouter_models,
        price_table: Callable[[], Mapping[str, dict]] = _litellm_price_table,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._listing = listing
        self._reference = reference
        self._price_table = price_table
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: dict[tuple, tuple[float, list[CatalogModel]]] = {}
        self._benchmarks: tuple[float, dict[str, float]] | None = None

    def _benchmark_index(self) -> dict[str, float]:
        now = self._clock()
        if self._benchmarks is None or now - self._benchmarks[0] > TTL_SECONDS:
            self._benchmarks = (now, benchmark_index(self._reference()))
        return self._benchmarks[1]

    def models(self, provider: Provider, api_key: str | None) -> list[CatalogModel]:
        """The provider's catalog; raises ``ModelListError`` when the provider does not list its models."""
        # A changed key or address is another catalog: what one key may call is not what another may.
        cache_key = (provider.id, provider.kind, provider.base_url, provider.key_last4)
        with self._lock:
            cached = self._entries.get(cache_key)
            if cached is not None and self._clock() - cached[0] <= TTL_SECONDS:
                return cached[1]
        body = self._listing(provider, api_key)
        with self._lock:
            models = build(provider, body, price_table=self._price_table(), benchmarks=self._benchmark_index())
            self._entries[cache_key] = (self._clock(), models)
        return models


__all__ = ["Catalog", "CatalogModel", "ModelListError", "build", "benchmark_index", "service_of", "with_latency"]
