"""A scripted LLM client that records every call for assertions."""

from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel

from app.llm.client import check_alias


@dataclass
class LLMCall:
    method: str
    alias: str
    prompt: str
    schema: type[BaseModel] | None = None


class FakeLLMClient:
    """Returns queued replies in order; a reply may be an exception to raise.

    Structured replies are dictionaries validated into the requested schema,
    or a callable that receives the prompt and returns one.
    """

    def __init__(self, replies: list[object] | None = None):
        self.replies = list(replies or [])
        self.calls: list[LLMCall] = []

    def _next(self, prompt: str) -> object:
        if not self.replies:
            raise AssertionError("FakeLLMClient has no reply left")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply(prompt) if isinstance(reply, Callable) else reply

    def structured(self, alias, prompt, schema):
        check_alias(alias)
        self.calls.append(LLMCall("structured", alias, prompt, schema))
        reply = self._next(prompt)
        return reply if isinstance(reply, schema) else schema.model_validate(reply)

    def text(self, alias, prompt):
        check_alias(alias)
        self.calls.append(LLMCall("text", alias, prompt))
        return str(self._next(prompt))
