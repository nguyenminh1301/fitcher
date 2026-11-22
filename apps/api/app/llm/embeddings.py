"""The embedding client contract of the ``embed`` tier, and its error type.

``app/llm/clients.py`` returns either the local model (``local_embeddings``)
or a provider's model through the gateway (``GatewayEmbeddings``). Unit tests
use a fake client, so no test downloads a model or sends a billable request.
"""

from collections.abc import Sequence
from typing import Protocol


class EmbeddingError(RuntimeError):
    """The embedding request failed or returned vectors of the wrong shape."""


class EmbeddingClient(Protocol):
    dimensions: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one vector of ``dimensions`` floats per text, in order."""
