"""Embeddings computed inside the api with fastembed (DECISIONS §2, §14): no key, no provider call.

The model is an ONNX export run on CPU. It is downloaded from Hugging Face on
first use into ``<FITCHER_DATA_DIR>/models``, so it survives restarts and is
part of the data volume's backup; fastembed and onnxruntime are imported only
then. The texts never leave the process, so the gateway's screening of
provider requests does not apply; documents and column values are still
screened before they are indexed (DECISIONS §9).
"""

from collections.abc import Callable, Sequence
import os
from pathlib import Path
import threading
from typing import Any

from app.llm.embeddings import EmbeddingError
from app.state.db import data_dir

# The multilingual models offered, with the vector size each returns.
LOCAL_MODELS = {
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2": 384,
    "sentence-transformers/paraphrase-multilingual-mpnet-base-v2": 768,
}
BATCH_SIZE = 64


def model_cache_dir() -> Path:
    return data_dir() / "models"


def _fastembed(name: str, cache_dir: str) -> Any:
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    from fastembed import TextEmbedding  # noqa: PLC0415 - imports onnxruntime; only when a local model is used

    return TextEmbedding(model_name=name, cache_dir=cache_dir)


class LocalEmbeddings:
    """``dimensions`` floats per text from a fastembed model, loaded once on first use."""

    def __init__(self, model: str, dimensions: int, cache_dir: Path | None = None,
                 loader: Callable[[str, str], Any] | None = None):
        self.model = model
        self.dimensions = dimensions
        self._cache_dir = cache_dir
        self._loader = loader
        self._loaded: Any = None
        self._lock = threading.Lock()

    def _engine(self) -> Any:
        with self._lock:
            if self._loaded is None:
                cache_dir = self._cache_dir or model_cache_dir()
                try:
                    cache_dir.mkdir(parents=True, exist_ok=True)
                    self._loaded = (self._loader or _fastembed)(self.model, str(cache_dir))
                except Exception as error:  # noqa: BLE001 - download, disk or ONNX failure
                    raise EmbeddingError(
                        f"cannot load the local embedding model {self.model}: {type(error).__name__}"
                    ) from None
            return self._loaded

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            vectors = [[float(value) for value in vector] for vector in self._engine().embed(list(texts), batch_size=BATCH_SIZE)]
        except EmbeddingError:
            raise
        except Exception as error:  # noqa: BLE001 - an ONNX runtime failure
            raise EmbeddingError(f"the local embedding model {self.model} failed: {type(error).__name__}") from None
        if len(vectors) != len(texts):
            raise EmbeddingError(f"model {self.model} returned {len(vectors)} vectors for {len(texts)} texts")
        for vector in vectors:
            if len(vector) != self.dimensions:
                raise EmbeddingError(
                    f"model {self.model} returned {len(vector)} dimensions; the embedding setting is {self.dimensions}"
                )
        return vectors
