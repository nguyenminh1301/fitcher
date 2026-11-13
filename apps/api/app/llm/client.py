"""The chat client contract every node uses, and its error types.

Engine code names a tier (``fast``, ``sql-small``, ``sql-gen`` or
``sql-gen-hard``), never a model; ``app/llm/gateway.py`` resolves it and
calls the provider. ``structured`` asks for JSON matching a Pydantic model and
validates the reply; ``text`` returns plain text. Every call sends a
``Prompt``: its instructions as the ``system`` message and the untrusted
content (question, history, definitions, rows) as the ``user`` message
(DECISIONS §9). A call the gateway's screening refuses raises
``GatewayBlocked``, which ends the run with the blocked reply instead of
being handled as an ordinary failed call. Unit tests use a fake client, so no
test sends a billable request.
"""

from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel


ModelT = TypeVar("ModelT", bound=BaseModel)


class LLMError(RuntimeError):
    """The gateway call failed or the reply did not match the requested schema."""


class GatewayBlocked(Exception):
    """The gateway's screening refused the call; deliberately not an ``LLMError``."""


@dataclass(frozen=True)
class Prompt:
    """One rendered prompt: the instructions, and the untrusted content they apply to."""

    system: str
    user: str

    @property
    def text(self) -> str:
        """Both parts as one text, for logs and test assertions."""
        return f"{self.system}\n\n{self.user}"


class LLMClient(Protocol):
    def structured(self, tier: str, prompt: Prompt, schema: type[ModelT]) -> ModelT:
        """Return the reply of ``tier``'s model parsed into ``schema``."""

    def text(self, tier: str, prompt: Prompt) -> str:
        """Return the reply text of ``tier``'s model."""
