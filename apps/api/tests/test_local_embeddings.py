"""The local embedding backend with a fake model in place of fastembed; no model is downloaded."""

import numpy as np
import pytest

from app.llm.embeddings import EmbeddingError
from app.llm.local_embeddings import LOCAL_MODELS, LocalEmbeddings, model_cache_dir


class FakeModel:
    def __init__(self, size: int):
        self.size = size
        self.batches: list[list[str]] = []

    def embed(self, documents, batch_size=256):
        documents = list(documents)
        self.batches.append(documents)
        return [np.full(self.size, float(len(text)), dtype=np.float32) for text in documents]


def test_texts_are_embedded_in_order_as_plain_floats(tmp_path):
    model = FakeModel(384)
    loads: list[tuple[str, str]] = []

    def loader(name: str, cache_dir: str):
        loads.append((name, cache_dir))
        return model

    embeddings = LocalEmbeddings("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", 384, tmp_path,
                                 loader=loader)
    vectors = embeddings.embed(["a", "bbb"])

    assert [vector[0] for vector in vectors] == [1.0, 3.0]
    assert all(type(value) is float for value in vectors[0]) and len(vectors[1]) == 384
    assert loads == [("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", str(tmp_path))]


def test_the_model_loads_once_on_first_use(tmp_path):
    loads = []
    embeddings = LocalEmbeddings("m", 4, tmp_path, loader=lambda name, cache_dir: loads.append(name) or FakeModel(4))

    assert loads == []
    embeddings.embed(["a"])
    embeddings.embed(["b"])

    assert loads == ["m"]


def test_a_model_of_another_size_is_refused(tmp_path):
    embeddings = LocalEmbeddings("m", 384, tmp_path, loader=lambda name, cache_dir: FakeModel(768))

    with pytest.raises(EmbeddingError, match="768 dimensions"):
        embeddings.embed(["a"])


def test_a_model_that_cannot_load_raises_embedding_error(tmp_path):
    def broken(name, cache_dir):
        raise OSError("no space left on device")

    with pytest.raises(EmbeddingError, match="cannot load the local embedding model m: OSError"):
        LocalEmbeddings("m", 4, tmp_path, loader=broken).embed(["a"])


def test_nothing_to_embed_loads_nothing(tmp_path):
    def never(name, cache_dir):
        raise AssertionError("loaded")

    assert LocalEmbeddings("m", 4, tmp_path, loader=never).embed([]) == []


def test_the_models_live_in_the_data_volume(monkeypatch, tmp_path):
    monkeypatch.setenv("FITCHER_DATA_DIR", str(tmp_path))

    assert model_cache_dir() == tmp_path / "models"


def test_the_offered_models_are_multilingual_with_their_vector_size():
    assert LOCAL_MODELS["sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"] == 384
    assert LOCAL_MODELS["sentence-transformers/paraphrase-multilingual-mpnet-base-v2"] == 768
