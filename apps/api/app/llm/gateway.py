"""The only code that calls a model provider: the LiteLLM SDK inside the api (DECISIONS §2, §9).

Engine code names a tier; a ``RouteResolver`` turns it into a ``Route``: the
provider's name, the LiteLLM model string (``openai/gpt-4.1-mini``,
``ollama_chat/qwen3:8b``) and the key or base URL to call it with. ``Gateway``
answers the chat tiers like the ``LLMClient`` protocol and
``GatewayEmbeddings`` the ``embed`` tier like ``EmbeddingClient``, with their
error types: a failed call raises ``LLMError`` or ``EmbeddingError`` naming
the model and the error type only, because a provider's message can quote the
request or part of the key.

Before any provider call the gateway checks screening (DECISIONS §9, Layer
0): the call must carry the ``screening`` metadata of ``llm_metadata`` (the
run's ``allow`` or ``flag`` verdict, or ``trusted_pack`` for reviewed pack
content outside a run), and the EN/VI rules of ``app/screening/rules.py`` run
again on every message and embedding input, as a safety net for content added
after the question was screened, such as history or result rows. A call that
fails either check raises ``GatewayBlocked`` naming the check and the rule ids,
never the text. This closes code paths that forgot to screen; it is not an
authentication boundary. The ``template_tag`` rule is skipped: the api's own
prompts put untrusted content between such tags.

Every call, answered, failed or refused, writes one ``llm_calls`` row through
``call_log`` (``app/llm/call_log.py``). Every call sets a timeout and bounded
retries and drops a parameter the model does not accept (such as a fixed
temperature) instead of failing.

LiteLLM is imported on the first call, not with this module: the import is
slow, and its price table is read from the copy inside the package instead of
being downloaded. Unit tests pass a fake in place of the SDK call.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import json
import os
import time
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from app.llm import call_log as calls
from app.llm.call_log import CallLog
from app.llm.client import GatewayBlocked, LLMError, Prompt
from app.llm.embeddings import EmbeddingError
from app.llm.tiers import check_chat_tier, EMBED_TIER
from app.observability.tracing import llm_metadata, TRUSTED_PACK
from app.screening import rules

TIMEOUT_SECONDS = 120
RETRIES = 2
BATCH_SIZE = 256

ModelT = TypeVar("ModelT", bound=BaseModel)
SCREENED = frozenset({"allow", "flag", TRUSTED_PACK})


@dataclass(frozen=True)
class Route:
    """Where one tier's calls go; ``api_key`` is the decrypted key and never leaves the gateway."""

    provider: str
    model: str
    api_key: str | None = None
    api_base: str | None = None

    def __repr__(self) -> str:
        return f"Route(provider={self.provider!r}, model={self.model!r}, api_base={self.api_base!r})"


class RouteResolver(Protocol):
    def route(self, tier: str) -> Route:
        """The route of ``tier`` now."""


def screening_rejection(screening: str | None, texts: Sequence[str]) -> str | None:
    """Why a call with this screening metadata and these texts is refused, or None when it may go out."""
    if not screening:
        return "the request carries no screening metadata"
    if screening not in SCREENED:
        return f"unknown screening value {screening[:40]!r}"
    hits = sorted({hit for text in texts for hit in rules.match(text, rules.GATEWAY_SKIPPED)})
    if hits:
        return f"the request trips screening rules {', '.join(hits)}"
    return None


def litellm_module():
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    import litellm  # noqa: PLC0415 - slow import, deferred to the first call

    litellm.suppress_debug_info = True
    return litellm


def _sdk_completion(**kwargs):
    return litellm_module().completion(**kwargs)


def _sdk_embedding(**kwargs):
    return litellm_module().embedding(**kwargs)


class _ProviderFailure(Exception):
    """The SDK call raised; carries only the error type's name."""


@dataclass(frozen=True)
class _Sender:
    """Screens one call, sends it through the SDK and writes its ``llm_calls`` row."""

    sdk: Callable[..., Any]
    call_type: str
    call_log: CallLog | None
    timeout: float
    retries: int

    def send(self, tier: str, route: Route, texts: Sequence[str], request: dict) -> Any:
        metadata = llm_metadata()
        started_at, started = calls.now(), time.monotonic()

        def log(status: str, error: str = "", response: Any = None, cost: float | None = None) -> None:
            calls.write(self.call_log, calls.call_record(
                metadata=metadata, tier=tier, provider=route.provider, model=route.model, started_at=started_at,
                latency_ms=round((time.monotonic() - started) * 1000), status=status, error=error,
                response=response, cost=cost,
            ))

        reason = screening_rejection(metadata.get("screening"), texts)
        if reason is not None:
            log("blocked", reason)
            raise GatewayBlocked(reason)
        try:
            response = self.sdk(
                model=route.model, api_key=route.api_key, api_base=route.api_base, timeout=self.timeout,
                num_retries=self.retries, drop_params=True, **request,
            )
        except Exception as error:  # noqa: BLE001 - every SDK and provider failure is reported by type only
            log("failure", type(error).__name__)
            raise _ProviderFailure(type(error).__name__) from None
        log("success", response=response, cost=calls.estimate_cost(response, route.model, self.call_type))
        return response


class Gateway:
    """Chat calls to a tier's model."""

    def __init__(
        self,
        resolver: RouteResolver,
        *,
        completion: Callable[..., Any] | None = None,
        call_log: CallLog | None = None,
        temperature: float | None = None,
        timeout: float = TIMEOUT_SECONDS,
        retries: int = RETRIES,
    ):
        self._resolver = resolver
        self._sender = _Sender(completion or _sdk_completion, "completion", call_log, timeout, retries)
        self._temperature = temperature

    def structured(self, tier: str, prompt: Prompt, schema: type[ModelT]) -> ModelT:
        response_format = {
            "type": "json_schema",
            "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema()},
        }
        model, content = self._complete(tier, prompt, response_format)
        try:
            return schema.model_validate(json.loads(content))
        except (json.JSONDecodeError, ValidationError):
            pass
        # Raised outside the handler: the validation details echo reply content, so the error keeps
        # neither them in its message nor the caught exception as its cause or context.
        raise LLMError(f"model {model} replied with JSON that does not match {schema.__name__}")

    def text(self, tier: str, prompt: Prompt) -> str:
        return self._complete(tier, prompt, None)[1]

    def _complete(self, tier: str, prompt: Prompt, response_format: dict | None) -> tuple[str, str]:
        """The model ``tier`` resolved to, and its reply text."""
        check_chat_tier(tier)
        route = self._resolver.route(tier)
        request: dict = {
            "messages": [{"role": "system", "content": prompt.system}, {"role": "user", "content": prompt.user}],
        }
        if response_format is not None:
            request["response_format"] = response_format
        if self._temperature is not None:
            request["temperature"] = self._temperature
        try:
            response = self._sender.send(tier, route, (prompt.system, prompt.user), request)
        except _ProviderFailure as failure:
            raise LLMError(f"request to model {route.model} failed: {failure}") from None
        choices = calls.field(response, "choices")
        message = calls.field(choices[0], "message") if isinstance(choices, list) and choices else None
        content = calls.field(message, "content")
        if content is not None and not isinstance(content, str):
            raise LLMError(f"model {route.model} returned a malformed reply")
        if not content or not content.strip():
            raise LLMError(f"model {route.model} returned an empty reply")
        return route.model, content


class GatewayEmbeddings:
    """Embeddings of the ``embed`` tier's model, ``dimensions`` floats per text."""

    def __init__(
        self,
        resolver: RouteResolver,
        dimensions: int,
        *,
        embedding: Callable[..., Any] | None = None,
        call_log: CallLog | None = None,
        batch_size: int = BATCH_SIZE,
        timeout: float = TIMEOUT_SECONDS,
        retries: int = RETRIES,
    ):
        self.dimensions = dimensions
        self._resolver = resolver
        self._sender = _Sender(embedding or _sdk_embedding, "embedding", call_log, timeout, retries)
        self._batch_size = batch_size

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            vectors.extend(self._embed_batch(list(texts[start:start + self._batch_size])))
        return vectors

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        route = self._resolver.route(EMBED_TIER)
        try:
            response = self._sender.send(EMBED_TIER, route, texts, {"input": texts, "dimensions": self.dimensions})
        except _ProviderFailure as failure:
            raise EmbeddingError(f"embedding request to model {route.model} failed: {failure}") from None
        data = sorted(calls.field(response, "data") or [], key=lambda item: calls.field(item, "index"))
        vectors = [list(calls.field(item, "embedding")) for item in data]
        if len(vectors) != len(texts):
            raise EmbeddingError(f"model {route.model} returned {len(vectors)} vectors for {len(texts)} texts")
        for vector in vectors:
            if len(vector) != self.dimensions:
                raise EmbeddingError(
                    f"model {route.model} returned {len(vector)} dimensions; the embedding setting is {self.dimensions}"
                )
        return vectors
