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
missing model or an empty reply moves to the next model. So does a request
one model rejected (400, 422, a context too long, Groq's "Failed to generate
JSON"): another model may take it, and nothing rests. A model that timed out, was
unavailable, is missing or needs credit the account lacks rests with that key
(``KeyPool.rest_model``), so the next calls skip it. When every model failed,
the ``LLMError`` lists each attempt. The SDK's own retries are off and each
tier has its own timeout (``TIER_TIMEOUTS``): the next key or model is the
retry, and a single model gets one more call only after a brief outage, never
after a timeout. The error type comes from the HTTP status, then from words of
the provider's message (``MESSAGE_TYPES``), which is never shown.

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
``call_log`` (``app/llm/call_log.py``). Every call sets a timeout and drops a parameter the model does not accept (such as a fixed
temperature) instead of failing.

LiteLLM is imported on the first call, not with this module: the import is
slow, its price table is read from the copy inside the package instead of
being downloaded, and it runs in production mode so it never loads a ``.env``
file into the environment. Unit tests pass a fake in place of the SDK call.
"""

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
import contextvars
from dataclasses import dataclass
import json
import os
import re
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
# How long one call to a chat tier's model may take before the chain moves on: a quick task gives up sooner.
TIER_TIMEOUTS = {"fast": 30.0, "sql-small": 45.0, "sql-gen": 90.0, "sql-gen-hard": 120.0}
# Chat calls are not retried by the SDK: a timeout retried on the same model only multiplies the wait. The next
# key or model is the retry; a single model is tried once more only after a transient failure that is not a timeout.
RETRIES = 0
EMBEDDING_RETRIES = 2
# A per-minute limit of an embedding provider is waited out when it asks for at most this many seconds, this many
# times per batch: Gemini's free tier embeds 100 texts a minute and answers HTTP 429 with a retryDelay under a minute.
EMBEDDING_WAIT_LIMIT = 65.0
EMBEDDING_WAITS = 3
# Calls made when a model's reply has no content, before the call fails.
EMPTY_REPLY_ATTEMPTS = 2
# Gemini refuses more than 100 texts in one embedding request ("at most 100 requests can be in one batch").
BATCH_SIZE = 100

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
STATUS_TYPES = {401: "AuthenticationError", 402: "PaymentRequiredError", 403: "PermissionDeniedError",
                429: "RateLimitError"}
PAYMENT_REQUIRED = "PaymentRequiredError"
QUOTA_EXCEEDED = "QuotaExceededError"
# Words of a provider's error message that tell what really happened when its status says something else; the
# first match wins. Z.ai answers a paid model on an account without credit with HTTP 429 "insufficient balance"
# (OpenAI with ``insufficient_quota``); Gemini answers a model whose free quota is used up with HTTP 429 "You
# exceeded your current quota", which holds for that model only; OpenRouter's daily allowance of free requests
# reads "free-models-per-day"; a provider's "overloaded" 429 is an outage of the model, not a limit of the key.
# The message is read here only to classify the error and is never shown or logged.
MESSAGE_TYPES = (
    (("insufficient balance", "insufficient_quota", "insufficient credit", "credit balance", "recharge",
      "no resource package", "payment required", "requires more credits"), PAYMENT_REQUIRED),
    (("exceeded your current quota", "quota exceeded", "resource_exhausted", "per-day", "per day"), QUOTA_EXCEEDED),
    (("overloaded", "over capacity", "temporarily unavailable", "high demand"), "ServiceUnavailableError"),
    (("rate limit", "too many requests"), "RateLimitError"),
)
# Types whose message is not read: a refused key stays a refused key whatever its message says.
_KEY_TYPES = frozenset({"AuthenticationError", "PermissionDeniedError"})


def error_type(error: Exception) -> str:
    """The SDK error's type name, or the type its HTTP status or message means when the SDK named another."""
    status = getattr(error, "status_code", None)
    kind = STATUS_TYPES.get(status, type(error).__name__) if isinstance(status, int) else type(error).__name__
    if kind in _KEY_TYPES:
        return kind
    try:
        message = str(error).lower()
    except Exception:  # noqa: BLE001 - an error that cannot be printed keeps its type
        return kind
    for words, meaning in MESSAGE_TYPES:
        if any(word in message for word in words):
            return meaning
    return kind


_RETRY_DELAY = re.compile(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"')


def _retry_after(error: Exception) -> float | None:
    """The seconds a rate-limited provider asked to wait: its Retry-After header, or Gemini's ``retryDelay``."""
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None) or getattr(error, "litellm_response_headers", None) or {}
    try:
        value = headers.get("retry-after") or headers.get("Retry-After")
        if value is not None:
            return float(value)
    except (AttributeError, TypeError, ValueError):
        pass
    found = _RETRY_DELAY.search(str(error))
    return float(found.group(1)) if found else None


# What the chain does after a failure, by the SDK's error type: try the provider's next key and rest or
# drop this one, stop because every model would get the same invalid request, or else move to the next model.
REST_KEY = frozenset({"RateLimitError"})
DROP_KEY = frozenset({"AuthenticationError", "PermissionDeniedError"})
# Failures of one model, not of the key: the model rests for this long (seconds), so the next calls of this run
# and of later runs go straight to the next model instead of waiting on it again.
REST_MODEL = {
    "Timeout": 60.0, "ServiceUnavailableError": 30.0, "APIConnectionError": 30.0, "InternalServerError": 30.0,
    "APIError": 30.0, PAYMENT_REQUIRED: 1800.0, QUOTA_EXCEEDED: 900.0, "NotFoundError": 1800.0, "EmptyReply": 60.0,
}
# Failures worth one more call to the same model when it is the only one: brief outages, never a timeout.
RETRY_SAME = frozenset({"ServiceUnavailableError", "APIConnectionError", "InternalServerError", "APIError"})
# A request one model rejected (400, 422, a context too long, a parameter it does not take, or Groq's "Failed to
# generate JSON") says nothing about the key or the next model: the next model is asked and nothing rests.
REQUEST_REJECTED = frozenset({
    "BadRequestError", "UnprocessableEntityError", "ContextWindowExceededError", "ContentPolicyViolationError",
    "UnsupportedParamsError",
})
EMPTY_REPLY = "EmptyReply"
INVALID_REPLY = "InvalidReply"
# What the chain does next after a failure it recovered from.
_NEXT_KEY, _NEXT_MODEL = object(), object()


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
    QUOTA_EXCEEDED: "the account's quota for this model is used up for now; the task's next model answers until it "
                    "resets, or add another provider or key on the Models page",
    INVALID_REPLY: "the model's reply did not match the answer format; another model may follow it better",
    "ContextWindowExceededError": "the request is longer than this model accepts; choose a model with a larger context",
    PAYMENT_REQUIRED: "the model is billed and the account has no credit for it; add credit or choose a free model "
                      "on the Models page",
}


def failure_text(error_type: str) -> str:
    """An error type with what to do about it, when that is known."""
    hint = FAILURE_HINTS.get(error_type)
    return f"{error_type} ({hint})" if hint else error_type


class Timeout(Exception):  # noqa: N818 - named like the SDK's own timeout so error_type reads it the same way
    """The whole call ran past its deadline."""


# The SDK's timeout bounds each wait for bytes, not the call: a provider that sends keep-alive lines (OpenRouter
# while a free model is queued) can hold a call for minutes. Calls run here so the caller stops waiting at the
# deadline; the abandoned call finishes in the background and its reply is dropped.
_CALLS = ThreadPoolExecutor(max_workers=32, thread_name_prefix="llm-call")
# A little time past the SDK's own timeout, so a provider that answers on time is never cut off.
DEADLINE_GRACE_SECONDS = 2.0


def within_deadline(call: Callable[[], Any], seconds: float) -> Any:
    """``call()``'s result, or ``Timeout`` once ``seconds`` have passed."""
    future = _CALLS.submit(contextvars.copy_context().run, call)
    try:
        return future.result(timeout=seconds)
    except FutureTimeout:
        future.cancel()
        raise Timeout(f"no answer within {seconds:.0f} s") from None


@dataclass(frozen=True)
class _Sender:
    """Screens one call, sends it through the SDK and writes its ``llm_calls`` row."""

    sdk: Callable[..., Any]
    call_type: str
    call_log: CallLog | None
    timeout: float
    retries: int

    def send(self, tier: str, route: Route, texts: Sequence[str], request: dict, *,
             retries: int | None = None, fallback_of: str = "", timeout: float | None = None) -> tuple[Any, str]:
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
        limit = self.timeout if timeout is None else timeout
        try:
            response = within_deadline(lambda: self.sdk(
                model=route.model, api_key=route.api_key, api_base=route.api_base, timeout=limit,
                num_retries=self.retries if retries is None else retries, drop_params=True, **request,
            ), limit * ((self.retries if retries is None else retries) + 1) + DEADLINE_GRACE_SECONDS)
        except Exception as error:  # noqa: BLE001 - every SDK and provider failure is reported by type only
            kind = error_type(error)
            call_id = log("failure", kind)
            raise _ProviderFailure(kind, _retry_after(error), call_id) from None
        call_id = log("success", response=response, cost=calls.estimate_cost(response, route.model, self.call_type, route.api_base))
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
    log("success", response=response, cost=calls.estimate_cost(response, route.model, "completion", route.api_base))
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
        timeout: float | None = None,
        retries: int = RETRIES,
        keys: KeyPool | None = None,
    ):
        """``timeout`` applies to every tier; without it each tier has its own (``TIER_TIMEOUTS``)."""
        self._resolver = resolver
        self._timeout = timeout
        self._sender = _Sender(completion or _sdk_completion, "completion", call_log,
                               timeout if timeout is not None else TIMEOUT_SECONDS, retries)
        self._temperature = temperature
        self._keys = keys or SHARED_KEYS

    def structured(self, tier: str, prompt: Prompt, schema: type[ModelT]) -> ModelT:
        response_format = {
            "type": "json_schema",
            "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema()},
        }
        parsed: list[ModelT] = []

        def accept(content: str) -> bool:
            # ValueError also covers a reply whose number is too long to read (a model repeating digits).
            try:
                parsed.append(schema.model_validate(json.loads(content)))
                return True
            except (ValueError, ValidationError, RecursionError):
                return False

        self._complete(tier, prompt, response_format, accept, schema.__name__)
        return parsed[-1]

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

    def _complete(self, tier: str, prompt: Prompt, response_format: dict | None,
                  accept: Callable[[str], bool] | None = None, schema_name: str = "") -> tuple[str, str]:
        """The model that answered ``tier``, and its reply text.

        A reply ``accept`` refuses (JSON that does not match the schema) fails that model like an error, and the
        chain's next model is asked.
        """
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
        timeout = self._timeout if self._timeout is not None else TIER_TIMEOUTS.get(tier, TIMEOUT_SECONDS)
        orders = [self._keys.order(routes) for routes in links]
        if not any(orders):
            # Every model rests after recent failures: try them again rather than fail without asking anyone.
            orders = links
        attempts: list[tuple[str, str]] = []
        previous = ""
        for routes, usable in zip(links, orders):
            if not usable:
                attempts.append((routes[0].model, "Resting"))
                continue
            for route in usable:
                tries = 2 if single else 1
                while tries:
                    tries -= 1
                    try:
                        content, previous = self._ask(tier, route, prompt, request, timeout, previous)
                    except _ProviderFailure as failure:
                        previous = failure.call_id
                        kind = failure.error_type
                        if tries and kind in RETRY_SAME:
                            continue
                        attempts.append((route.model, kind))
                        self._after_failure(route, failure)
                        if single:
                            raise LLMError(f"request to model {route.model} failed: {failure_text(kind)}",
                                           tuple(attempts)) from None
                        content = _NEXT_KEY if kind in REST_KEY or kind in DROP_KEY else _NEXT_MODEL
                    break
                if content is _NEXT_KEY:
                    continue
                if content is _NEXT_MODEL:
                    break
                if content is None:
                    attempts.append((route.model, EMPTY_REPLY))
                    self._keys.rest_model(route, REST_MODEL[EMPTY_REPLY])
                    if single:
                        raise LLMError(f"model {route.model} returned an empty reply", tuple(attempts))
                    break
                if accept is not None and not accept(content):
                    attempts.append((route.model, INVALID_REPLY))
                    if single:
                        # The reply is not quoted: it may echo the request.
                        raise LLMError(f"model {route.model} replied with JSON that does not match {schema_name}",
                                       tuple(attempts))
                    break
                self._keys.answered(route)
                return route.model, content
        raise LLMError(_attempts_text(tier, attempts), tuple(attempts))

    def _after_failure(self, route: Route, failure: "_ProviderFailure") -> None:
        """Rest or drop the key, or rest the model, by what failed; a rejected request rests nothing."""
        if failure.error_type in REQUEST_REJECTED:
            return
        if failure.error_type in REST_KEY:
            self._keys.rest(route, failure.retry_after)
        elif failure.error_type in DROP_KEY:
            self._keys.refuse(route)
        elif failure.error_type in REST_MODEL:
            self._keys.rest_model(route, REST_MODEL[failure.error_type])

    def _ask(self, tier: str, route: Route, prompt: Prompt, request: dict, timeout: float,
             fallback_of: str) -> tuple[str | None, str]:
        """The route's reply text, or None when it stayed empty, and the last call id logged."""
        # A reasoning model sometimes spends its whole reply on reasoning and returns no content; it is asked
        # once more before the route counts as failed.
        call_id = fallback_of
        for _ in range(EMPTY_REPLY_ATTEMPTS):
            response, call_id = self._sender.send(tier, route, (prompt.system, prompt.user), request,
                                                  fallback_of=fallback_of, timeout=timeout)
            choices = calls.field(response, "choices")
            message = calls.field(choices[0], "message") if isinstance(choices, list) and choices else None
            content = calls.field(message, "content")
            if content is not None and not isinstance(content, str):
                raise LLMError(f"model {route.model} returned a malformed reply")
            if content and content.strip():
                return content, call_id
        return None, call_id


# The failures of an embedding provider's request limit, and what to do when waiting did not help: a free key's
# limit (Gemini: 100 texts a minute, 1,000 a day) cannot index a pack with many column values.
EMBEDDING_LIMITS = frozenset({"RateLimitError", QUOTA_EXCEEDED})
EMBEDDING_LIMIT_HINT = ("the provider's embedding limit is used up, which a free key reaches on a pack with many "
                        "values; choose the local embedding model on the Models page, or use a paid key")


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
        retries: int = EMBEDDING_RETRIES,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.dimensions = dimensions
        self._resolver = resolver
        self._sender = _Sender(embedding or _sdk_embedding, "embedding", call_log, timeout, retries)
        self._batch_size = batch_size
        self._sleep = sleep

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
        waits = 0
        while True:
            try:
                response, _ = self._sender.send(EMBED_TIER, route, texts, {"input": texts, "dimensions": self.dimensions})
                break
            except _ProviderFailure as failure:
                limited = failure.error_type in EMBEDDING_LIMITS
                if limited and failure.retry_after is not None and failure.retry_after <= EMBEDDING_WAIT_LIMIT \
                        and waits < EMBEDDING_WAITS:
                    waits += 1
                    self._sleep(failure.retry_after + 1)
                    continue
                hint = f"{failure.error_type} ({EMBEDDING_LIMIT_HINT})" if limited else failure_text(failure.error_type)
                raise EmbeddingError(f"embedding request to model {route.model} failed: {hint}") from None
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
