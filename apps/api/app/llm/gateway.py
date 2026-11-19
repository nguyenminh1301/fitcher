"""The only code that calls a model provider: the LiteLLM SDK inside the api (DECISIONS §2, §9).

Engine code names a tier; a ``RouteResolver`` turns it into a ``Route``: the
provider's name, the LiteLLM model string (``openai/gpt-4.1-mini``,
``ollama_chat/qwen3:8b``) and the key or base URL to call it with. ``Gateway``
answers the chat tiers like the ``LLMClient`` protocol and
``GatewayEmbeddings`` the ``embed`` tier like ``EmbeddingClient``, with their
error types: a failed call raises ``LLMError`` or ``EmbeddingError`` naming
the model and the error type only, because a provider's message can quote the
request or part of the key.

A resolver that has ``chain(tier)`` gives a chat tier an ordered fallback
chain: each link is one model with one route per API key of its provider. The
gateway tries the keys of a link in the ``KeyPool``'s round-robin order; a
rate-limited key rests and a refused key is dropped, and the next key is
tried. A rate limit with no key left, a timeout, a connection error, a 5xx, a
missing model or an empty reply moves to the next model. A request the model
rejected as invalid (400, 422, a context too long) stops the chain, because
the next model would get the same request. When every model failed, the
``LLMError`` lists each attempt. With a chain the SDK's own retries are off:
the next key or model is the retry.

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
slow, its price table is read from the copy inside the package instead of
being downloaded, and it runs in production mode so it never loads a ``.env``
file into the environment. Unit tests pass a fake in place of the SDK call.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import json
import os
import time
from typing import Any, Protocol, TypeVar
import uuid

from pydantic import BaseModel, ValidationError

from app.llm import call_log as calls
from app.llm.call_log import CallLog
from app.llm.client import GatewayBlocked, LLMError, Prompt
from app.llm.embeddings import EmbeddingError
from app.llm.key_pool import KeyPool, SHARED as SHARED_KEYS
from app.llm.tiers import check_chat_tier, EMBED_TIER
from app.observability.tracing import llm_metadata, TRUSTED_PACK
from app.screening import rules

TIMEOUT_SECONDS = 120
RETRIES = 2
# Calls made when a model's reply has no content, before the call fails.
EMPTY_REPLY_ATTEMPTS = 2
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
    # The provider's key this route uses (``provider_keys``); None for a provider without keys.
    key_id: str | None = None

    def __repr__(self) -> str:
        return f"Route(provider={self.provider!r}, model={self.model!r}, api_base={self.api_base!r}, key_id={self.key_id!r})"


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
    # Outside production mode LiteLLM loads a .env file from the working directory into the environment
    # on import, which would hand the process every key and password that file holds.
    os.environ.setdefault("LITELLM_MODE", "PRODUCTION")
    import litellm  # noqa: PLC0415 - slow import, deferred to the first call

    litellm.suppress_debug_info = True
    return litellm


def _sdk_completion(**kwargs):
    return litellm_module().completion(**kwargs)


def _sdk_embedding(**kwargs):
    return litellm_module().embedding(**kwargs)


class _ProviderFailure(Exception):
    """The SDK call raised; carries only the error type's name, the provider's Retry-After and the logged call id."""

    def __init__(self, error_type: str, retry_after: float | None = None, call_id: str = ""):
        super().__init__(error_type)
        self.error_type = error_type
        self.retry_after = retry_after
        self.call_id = call_id


# Some OpenAI-compatible providers answer a refused key or a rate limit in a shape the SDK reports as another
# error type; the HTTP status is what the chain acts on.
STATUS_TYPES = {401: "AuthenticationError", 403: "PermissionDeniedError", 429: "RateLimitError"}


def error_type(error: Exception) -> str:
    """The SDK error's type name, or the type its HTTP status means when the SDK named another."""
    status = getattr(error, "status_code", None)
    return STATUS_TYPES.get(status, type(error).__name__) if isinstance(status, int) else type(error).__name__


def _retry_after(error: Exception) -> float | None:
    """The seconds a rate-limited provider asked to wait, from its Retry-After header."""
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None) or getattr(error, "litellm_response_headers", None) or {}
    try:
        value = headers.get("retry-after") or headers.get("Retry-After")
        return float(value) if value is not None else None
    except (AttributeError, TypeError, ValueError):
        return None


# What the chain does after a failure, by the SDK's error type: try the provider's next key and rest or
# drop this one, stop because every model would get the same invalid request, or else move to the next model.
REST_KEY = frozenset({"RateLimitError"})
DROP_KEY = frozenset({"AuthenticationError", "PermissionDeniedError"})
STOP_CHAIN = frozenset({
    "BadRequestError", "UnprocessableEntityError", "ContextWindowExceededError", "ContentPolicyViolationError",
    "UnsupportedParamsError",
})
EMPTY_REPLY = "EmptyReply"


# What a person can do about a provider failure, by the SDK's error type. The provider's own message is never
# shown: it can quote the key or the request.
FAILURE_HINTS = {
    "RateLimitError": "the provider is limiting requests; a free model's daily or per-minute limit may be used up. "
                      "Try again later or choose another model on the Models page",
    "AuthenticationError": "the provider refused the API key; enter it again on the Models page",
    "PermissionDeniedError": "the API key may not use this model; choose another model on the Models page",
    "NotFoundError": "the provider does not have this model; choose another model on the Models page",
    "Timeout": "the model took too long to answer; try again or choose a faster model on the Models page",
    "APIConnectionError": "the provider could not be reached; check its address and the network",
    "ServiceUnavailableError": "the provider is unavailable for now; try again later",
    "ContextWindowExceededError": "the request is longer than this model accepts; choose a model with a larger context",
}


def failure_text(error_type: str) -> str:
    """An error type with what to do about it, when that is known."""
    hint = FAILURE_HINTS.get(error_type)
    return f"{error_type} ({hint})" if hint else error_type


@dataclass(frozen=True)
class _Sender:
    """Screens one call, sends it through the SDK and writes its ``llm_calls`` row."""

    sdk: Callable[..., Any]
    call_type: str
    call_log: CallLog | None
    timeout: float
    retries: int

    def send(self, tier: str, route: Route, texts: Sequence[str], request: dict, *,
             retries: int | None = None, fallback_of: str = "") -> tuple[Any, str]:
        """The SDK's reply and the call id logged for it."""
        metadata = llm_metadata()
        started_at, started = calls.now(), time.monotonic()
        attempt_id = uuid.uuid4().hex

        def log(status: str, error: str = "", response: Any = None, cost: float | None = None) -> str:
            record = calls.call_record(
                metadata=metadata, tier=tier, provider=route.provider, model=route.model, started_at=started_at,
                latency_ms=round((time.monotonic() - started) * 1000), status=status, error=error,
                response=response, cost=cost, fallback_of=fallback_of, call_id=attempt_id,
            )
            calls.write(self.call_log, record)
            return record.call_id

        reason = screening_rejection(metadata.get("screening"), texts)
        if reason is not None:
            log("blocked", reason)
            raise GatewayBlocked(reason)
        try:
            response = self.sdk(
                model=route.model, api_key=route.api_key, api_base=route.api_base, timeout=self.timeout,
                num_retries=self.retries if retries is None else retries, drop_params=True, **request,
            )
        except Exception as error:  # noqa: BLE001 - every SDK and provider failure is reported by type only
            kind = error_type(error)
            call_id = log("failure", kind)
            raise _ProviderFailure(kind, _retry_after(error), call_id) from None
        call_id = log("success", response=response, cost=calls.estimate_cost(response, route.model, self.call_type))
        return response, call_id


def _attempts_text(tier: str, attempts: Sequence[tuple[str, str]]) -> str:
    listed = "; ".join(f"{model}: {failure_text(reason)}" for model, reason in attempts)
    return f"every model of the {tier} tier failed: {listed}"


CLASSIFIER_TIER = "screen"


def classifier_reply(route: Route, text: str, *, call_log: CallLog | None = None,
                     completion: Callable[..., Any] | None = None, timeout: float = 30.0, retries: int = 1) -> str:
    """The reply of a prompt-injection classifier model (such as Llama Prompt Guard) to one untrusted text.

    This is the screen itself, so the text is sent as it is: the screening metadata and rules checks that guard
    the answering models do not apply, and nothing else is added to the request. The model answers with a score,
    never with text that reaches another model. The call writes its ``llm_calls`` row under the ``screen`` tier.
    """
    started_at, started = calls.now(), time.monotonic()

    def log(status: str, error: str = "", response: Any = None, cost: float | None = None) -> None:
        calls.write(call_log, calls.call_record(
            metadata=llm_metadata(), tier=CLASSIFIER_TIER, provider=route.provider, model=route.model,
            started_at=started_at, latency_ms=round((time.monotonic() - started) * 1000), status=status, error=error,
            response=response, cost=cost, call_id=uuid.uuid4().hex,
        ))

    try:
        response = (completion or _sdk_completion)(
            model=route.model, api_key=route.api_key, api_base=route.api_base, timeout=timeout, num_retries=retries,
            drop_params=True, messages=[{"role": "user", "content": text}],
        )
    except Exception as error:  # noqa: BLE001 - reported by type only, like every provider failure
        kind = error_type(error)
        log("failure", kind)
        raise LLMError(f"classifier model {route.model} failed: {failure_text(kind)}") from None
    log("success", response=response, cost=calls.estimate_cost(response, route.model, "completion"))
    choices = calls.field(response, "choices")
    message = calls.field(choices[0], "message") if isinstance(choices, list) and choices else None
    content = calls.field(message, "content")
    if not isinstance(content, str):
        raise LLMError(f"classifier model {route.model} returned no score")
    return content


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
        keys: KeyPool | None = None,
    ):
        self._resolver = resolver
        self._sender = _Sender(completion or _sdk_completion, "completion", call_log, timeout, retries)
        self._temperature = temperature
        self._keys = keys or SHARED_KEYS

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

    def _links(self, tier: str) -> list[list[Route]]:
        """The tier's chain: per model, one route per key; a resolver without chains gives one model."""
        try:
            chain = getattr(self._resolver, "chain", None)
            links = chain(tier) if chain is not None else [[self._resolver.route(tier)]]
        except LookupError as error:  # no model mapped to the tier, or its provider is gone
            raise LLMError(str(error)) from None
        links = [routes for routes in links if routes]
        if not links:
            raise LLMError(f"no model is mapped to the {tier} tier; add a provider on the Models page")
        return links

    def _complete(self, tier: str, prompt: Prompt, response_format: dict | None) -> tuple[str, str]:
        """The model that answered ``tier``, and its reply text."""
        check_chat_tier(tier)
        links = self._links(tier)
        request: dict = {
            "messages": [{"role": "system", "content": prompt.system}, {"role": "user", "content": prompt.user}],
        }
        if response_format is not None:
            request["response_format"] = response_format
        if self._temperature is not None:
            request["temperature"] = self._temperature
        single = len(links) == 1 and len(links[0]) == 1
        attempts: list[tuple[str, str]] = []
        previous = ""
        for routes in links:
            usable = self._keys.order(routes)
            if not usable:
                attempts.append((routes[0].model, "RateLimitError"))
                continue
            for route in usable:
                try:
                    content, previous = self._ask(tier, route, prompt, request, None if single else 0, previous)
                except _ProviderFailure as failure:
                    previous = failure.call_id
                    attempts.append((route.model, failure.error_type))
                    if single or failure.error_type in STOP_CHAIN:
                        raise LLMError(f"request to model {route.model} failed: {failure_text(failure.error_type)}",
                                       tuple(attempts)) from None
                    if failure.error_type in REST_KEY:
                        self._keys.rest(route, failure.retry_after)
                        continue
                    if failure.error_type in DROP_KEY:
                        self._keys.refuse(route)
                        continue
                    break
                if content is None:
                    attempts.append((route.model, EMPTY_REPLY))
                    if single:
                        raise LLMError(f"model {route.model} returned an empty reply", tuple(attempts))
                    break
                return route.model, content
        raise LLMError(_attempts_text(tier, attempts), tuple(attempts))

    def _ask(self, tier: str, route: Route, prompt: Prompt, request: dict, retries: int | None,
             fallback_of: str) -> tuple[str | None, str]:
        """The route's reply text, or None when it stayed empty, and the last call id logged."""
        # A reasoning model sometimes spends its whole reply on reasoning and returns no content; it is asked
        # once more before the route counts as failed.
        call_id = fallback_of
        for _ in range(EMPTY_REPLY_ATTEMPTS):
            response, call_id = self._sender.send(tier, route, (prompt.system, prompt.user), request,
                                                  retries=retries, fallback_of=fallback_of)
            choices = calls.field(response, "choices")
            message = calls.field(choices[0], "message") if isinstance(choices, list) and choices else None
            content = calls.field(message, "content")
            if content is not None and not isinstance(content, str):
                raise LLMError(f"model {route.model} returned a malformed reply")
            if content and content.strip():
                return content, call_id
        return None, call_id


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
        try:
            route = self._resolver.route(EMBED_TIER)
        except LookupError as error:  # no embedding model set, or its provider is gone
            raise EmbeddingError(str(error)) from None
        try:
            response, _ = self._sender.send(EMBED_TIER, route, texts, {"input": texts, "dimensions": self.dimensions})
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
