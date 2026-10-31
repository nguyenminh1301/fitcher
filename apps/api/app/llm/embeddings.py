"""Embeddings through the LiteLLM ``embed`` alias.

Engine code only ever names the alias; LiteLLM maps it to a model. Unit tests
use a fake client, so no test sends a billable request.
"""

from collections.abc import Sequence
from typing import Protocol

import httpx

EMBED_ALIAS = "embed"
BATCH_SIZE = 256
TIMEOUT_SECONDS = 120


class EmbeddingError(RuntimeError):
    """The embedding request failed or returned vectors of the wrong shape."""


class EmbeddingClient(Protocol):
    dimensions: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one vector of ``dimensions`` floats per text, in order."""


class LiteLLMEmbeddings:
    """OpenAI-compatible ``/v1/embeddings`` calls to the ``embed`` alias."""

    def __init__(self, base_url: str, api_key: str, dimensions: int, http: httpx.Client | None = None):
        if not base_url or not api_key:
            raise EmbeddingError("LITELLM_BASE_URL and LITELLM_MASTER_KEY must be set")
        self.dimensions = dimensions
        self._url = f"{base_url.rstrip('/')}/v1/embeddings"
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._http = http or httpx.Client(timeout=TIMEOUT_SECONDS)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), BATCH_SIZE):
            vectors.extend(self._embed_batch(list(texts[start:start + BATCH_SIZE])))
        return vectors

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        payload = {"model": EMBED_ALIAS, "input": texts, "dimensions": self.dimensions}
        try:
            response = self._http.post(self._url, json=payload, headers=self._headers)
        except httpx.HTTPError as error:
            raise EmbeddingError(f"embedding request to alias {EMBED_ALIAS} failed: {type(error).__name__}") from error
        if response.status_code != 200:
            raise EmbeddingError(f"alias {EMBED_ALIAS} returned HTTP {response.status_code}")
        data = sorted(response.json().get("data", []), key=lambda item: item["index"])
        vectors = [item["embedding"] for item in data]
        if len(vectors) != len(texts):
            raise EmbeddingError(f"alias {EMBED_ALIAS} returned {len(vectors)} vectors for {len(texts)} texts")
        for vector in vectors:
            if len(vector) != self.dimensions:
                raise EmbeddingError(
                    f"alias {EMBED_ALIAS} returned {len(vector)} dimensions; EMBEDDING_DIMENSIONS is {self.dimensions}"
                )
        return vectors
