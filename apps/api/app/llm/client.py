"""Chat calls to a model tier through the LiteLLM catalog.

Engine code names a tier (``fast``, ``sql-small``, ``sql-gen`` or
``sql-gen-hard``), never a model: ``TierMap`` turns it into a catalog alias
and LiteLLM maps the alias to a model. ``structured`` asks for
JSON matching a Pydantic model and validates the reply; ``text`` returns plain
text. Every call sends a ``Prompt``: its instructions as the ``system``
message and the untrusted content (question, history, definitions, rows) as
the ``user`` message (DECISIONS §9). Inside a traced run each request carries
the run's ``trace_id``, node and ``screening`` verdict as LiteLLM metadata;
every request also carries its ``tier``. The proxy callback writes both to
``llm_calls``. A request the gateway's
screening guardrail rejects raises ``GatewayBlocked``, which ends the run with
the blocked reply instead of being handled as an ordinary failed call. Unit
tests use a fake client, so no test sends a billable request.
"""

from dataclasses import dataclass
import json
from typing import Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.llm.tiers import BUILT_IN_DEFAULTS, check_chat_tier, TierMap
from app.observability.tracing import llm_metadata

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
    def structured(self, tier: str, prompt: Prompt, schema: type[ModelT]) -> ModelT:
        """Return the reply of ``tier``'s model parsed into ``schema``."""

    def text(self, tier: str, prompt: Prompt) -> str:
        """Return the reply text of ``tier``'s model."""


class LiteLLMClient:
    """OpenAI-compatible ``/v1/chat/completions`` calls through the LiteLLM proxy."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        http: httpx.Client | None = None,
        temperature: float | None = None,
        tiers: TierMap | None = None,
    ):
        """``temperature`` is sent with every call when set; the proxy drops it for models that reject it.

        ``tiers`` resolves each tier to its alias; without it the built-in defaults apply.
        """
        if not base_url or not api_key:
            raise LLMError("LITELLM_BASE_URL and LITELLM_MASTER_KEY must be set")
        self._url = f"{base_url.rstrip('/')}/v1/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._http = http or httpx.Client(timeout=TIMEOUT_SECONDS)
        self._temperature = temperature
        self.tiers = tiers or TierMap(BUILT_IN_DEFAULTS)

    def structured(self, tier: str, prompt: Prompt, schema: type[ModelT]) -> ModelT:
        response_format = {
            "type": "json_schema",
            "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema()},
        }
        alias, content = self._complete(tier, prompt, response_format)
        try:
            return schema.model_validate(json.loads(content))
        except (json.JSONDecodeError, ValidationError):
            pass
        # Raised outside the handler: the validation details echo reply content, so the error keeps
        # neither them in its message nor the caught exception as its cause or context.
        raise LLMError(f"alias {alias} replied with JSON that does not match {schema.__name__}")

    def text(self, tier: str, prompt: Prompt) -> str:
        return self._complete(tier, prompt, None)[1]

    def _complete(self, tier: str, prompt: Prompt, response_format: dict | None) -> tuple[str, str]:
        """The alias ``tier`` resolved to, and its reply text."""
        check_chat_tier(tier)
        alias = self.tiers.alias(tier)
        messages = [{"role": "system", "content": prompt.system}, {"role": "user", "content": prompt.user}]
        payload: dict = {"model": alias, "messages": messages}
        if response_format is not None:
            payload["response_format"] = response_format
        if self._temperature is not None:
            payload["temperature"] = self._temperature
        payload["metadata"] = {**llm_metadata(), "tier": tier}
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
        return alias, content
