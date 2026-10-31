"""Chat calls to the LiteLLM aliases.

Engine code names an alias, never a model: LiteLLM maps ``fast``, ``sql-gen``
and ``sql-gen-hard`` to models from its configuration. ``structured`` asks for
JSON matching a Pydantic model and validates the reply; ``text`` returns plain
text. Unit tests use a fake client, so no test sends a billable request.
"""

import json
from typing import Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

CHAT_ALIASES = frozenset({"fast", "sql-gen", "sql-gen-hard"})
TIMEOUT_SECONDS = 120

ModelT = TypeVar("ModelT", bound=BaseModel)


class LLMError(RuntimeError):
    """The gateway call failed or the reply did not match the requested schema."""


class LLMClient(Protocol):
    def structured(self, alias: str, prompt: str, schema: type[ModelT]) -> ModelT:
        """Return the reply parsed into ``schema``."""

    def text(self, alias: str, prompt: str) -> str:
        """Return the reply text."""


def check_alias(alias: str) -> None:
    if alias not in CHAT_ALIASES:
        raise ValueError(f"unknown LLM alias {alias!r}; use one of {sorted(CHAT_ALIASES)}")


class LiteLLMClient:
    """OpenAI-compatible ``/v1/chat/completions`` calls through the LiteLLM proxy."""

    def __init__(self, base_url: str, api_key: str, http: httpx.Client | None = None):
        if not base_url or not api_key:
            raise LLMError("LITELLM_BASE_URL and LITELLM_MASTER_KEY must be set")
        self._url = f"{base_url.rstrip('/')}/v1/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._http = http or httpx.Client(timeout=TIMEOUT_SECONDS)

    def structured(self, alias: str, prompt: str, schema: type[ModelT]) -> ModelT:
        response_format = {
            "type": "json_schema",
            "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema()},
        }
        content = self._complete(alias, prompt, response_format)
        try:
            return schema.model_validate(json.loads(content))
        except (json.JSONDecodeError, ValidationError) as error:
            raise LLMError(f"alias {alias} replied with JSON that does not match {schema.__name__}: {error}") from error

    def text(self, alias: str, prompt: str) -> str:
        return self._complete(alias, prompt, None)

    def _complete(self, alias: str, prompt: str, response_format: dict | None) -> str:
        check_alias(alias)
        payload: dict = {"model": alias, "messages": [{"role": "user", "content": prompt}]}
        if response_format is not None:
            payload["response_format"] = response_format
        try:
            response = self._http.post(self._url, json=payload, headers=self._headers)
        except httpx.HTTPError as error:
            raise LLMError(f"request to alias {alias} failed: {type(error).__name__}") from error
        if response.status_code != 200:
            raise LLMError(f"alias {alias} returned HTTP {response.status_code}")
        choices = response.json().get("choices") or [{}]
        content = (choices[0].get("message") or {}).get("content") or ""
        if not content.strip():
            raise LLMError(f"alias {alias} returned an empty reply")
        return content
