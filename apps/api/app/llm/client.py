"""Chat calls to the LiteLLM aliases.

Engine code names an alias, never a model: LiteLLM maps ``fast``, ``sql-gen``
and ``sql-gen-hard`` to models from its configuration. ``structured`` asks for
JSON matching a Pydantic model and validates the reply; ``text`` returns plain
text. Every call sends a ``Prompt``: its instructions as the ``system``
message and the untrusted content (question, history, definitions, rows) as
the ``user`` message (DECISIONS §9). Inside a traced run each request carries
the run's ``trace_id``, node and ``screening`` verdict as LiteLLM metadata,
which the proxy callback writes to ``llm_calls``. A request the gateway's
screening guardrail rejects raises ``GatewayBlocked``, which ends the run with
the blocked reply instead of being handled as an ordinary failed call. Unit
tests use a fake client, so no test sends a billable request.
"""

from dataclasses import dataclass
import json
from typing import Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.observability.tracing import llm_metadata

CHAT_ALIASES = frozenset({"fast", "sql-gen", "sql-gen-hard"})
TIMEOUT_SECONDS = 120
# The gateway guardrail starts every rejection with this (infra/litellm/callbacks/screening_guard.py).
GATEWAY_MARKER = "screening_guard"

ModelT = TypeVar("ModelT", bound=BaseModel)


class LLMError(RuntimeError):
    """The gateway call failed or the reply did not match the requested schema."""


class GatewayBlocked(Exception):
    """The gateway's screening guardrail rejected the request; deliberately not an ``LLMError``."""


@dataclass(frozen=True)
class Prompt:
    """One rendered prompt: the instructions, and the untrusted content they apply to."""

    system: str
    user: str

    @property
    def text(self) -> str:
        """Both parts as one text, for logs and test assertions."""
        return f"{self.system}\n\n{self.user}"


def check_gateway(response: httpx.Response) -> None:
    """Raise ``GatewayBlocked`` when ``response`` is the screening guardrail's rejection."""
    if response.status_code != 200 and GATEWAY_MARKER in response.text:
        raise GatewayBlocked(f"the gateway rejected the request with HTTP {response.status_code}")


class LLMClient(Protocol):
    def structured(self, alias: str, prompt: Prompt, schema: type[ModelT]) -> ModelT:
        """Return the reply parsed into ``schema``."""

    def text(self, alias: str, prompt: Prompt) -> str:
        """Return the reply text."""


def check_alias(alias: str) -> None:
    if alias not in CHAT_ALIASES:
        raise ValueError(f"unknown LLM alias {alias!r}; use one of {sorted(CHAT_ALIASES)}")


class LiteLLMClient:
    """OpenAI-compatible ``/v1/chat/completions`` calls through the LiteLLM proxy."""

    def __init__(
        self, base_url: str, api_key: str, http: httpx.Client | None = None, temperature: float | None = None
    ):
        """``temperature`` is sent with every call when set; the proxy drops it for models that reject it."""
        if not base_url or not api_key:
            raise LLMError("LITELLM_BASE_URL and LITELLM_MASTER_KEY must be set")
        self._url = f"{base_url.rstrip('/')}/v1/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._http = http or httpx.Client(timeout=TIMEOUT_SECONDS)
        self._temperature = temperature

    def structured(self, alias: str, prompt: Prompt, schema: type[ModelT]) -> ModelT:
        response_format = {
            "type": "json_schema",
            "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema()},
        }
        content = self._complete(alias, prompt, response_format)
        try:
            return schema.model_validate(json.loads(content))
        except (json.JSONDecodeError, ValidationError):
            pass
        # Raised outside the handler: the validation details echo reply content, so the error keeps
        # neither them in its message nor the caught exception as its cause or context.
        raise LLMError(f"alias {alias} replied with JSON that does not match {schema.__name__}")

    def text(self, alias: str, prompt: Prompt) -> str:
        return self._complete(alias, prompt, None)

    def _complete(self, alias: str, prompt: Prompt, response_format: dict | None) -> str:
        check_alias(alias)
        messages = [{"role": "system", "content": prompt.system}, {"role": "user", "content": prompt.user}]
        payload: dict = {"model": alias, "messages": messages}
        if response_format is not None:
            payload["response_format"] = response_format
        if self._temperature is not None:
            payload["temperature"] = self._temperature
        if metadata := llm_metadata():
            payload["metadata"] = metadata
        try:
            response = self._http.post(self._url, json=payload, headers=self._headers)
        except httpx.HTTPError as error:
            raise LLMError(f"request to alias {alias} failed: {type(error).__name__}") from error
        check_gateway(response)
        if response.status_code != 200:
            raise LLMError(f"alias {alias} returned HTTP {response.status_code}")
        try:
            envelope = response.json()
        except ValueError as error:
            raise LLMError(f"alias {alias} returned a reply that is not JSON") from error
        choices = envelope.get("choices") if isinstance(envelope, dict) else None
        first = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
        message = first.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if content is not None and not isinstance(content, str):
            raise LLMError(f"alias {alias} returned a malformed reply")
        if not content or not content.strip():
            raise LLMError(f"alias {alias} returned an empty reply")
        return content
