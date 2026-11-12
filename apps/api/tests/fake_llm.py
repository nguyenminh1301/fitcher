"""A scripted LLM client that records every call for assertions."""

from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel

from app.llm.client import Prompt
from app.llm.tiers import check_chat_tier


@dataclass
class LLMCall:
    method: str
    tier: str
    # Both parts of the prompt as one text; ``system`` and ``user`` keep them apart.
    prompt: str
    schema: type[BaseModel] | None = None
    system: str = ""
    user: str = ""


class FakeLLMClient:
    """Returns queued replies in order; a reply may be an exception to raise.

    Structured replies are dictionaries validated into the requested schema,
    or a callable that receives the prompt text and returns one.
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

    def _record(self, method: str, tier: str, prompt: Prompt, schema=None) -> str:
        assert isinstance(prompt, Prompt), "LLM calls send a Prompt with system and user parts"
        check_chat_tier(tier)
        self.calls.append(LLMCall(method, tier, prompt.text, schema, prompt.system, prompt.user))
        return prompt.text

    def structured(self, tier, prompt, schema):
        reply = self._next(self._record("structured", tier, prompt, schema))
        return reply if isinstance(reply, schema) else schema.model_validate(reply)

    def text(self, tier, prompt):
        return str(self._next(self._record("text", tier, prompt)))
