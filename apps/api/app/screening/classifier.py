"""The local prompt-injection classifier: an ONNX model and its tokenizer (DECISIONS §9, Layer 0).

``jobs/fetch_guard_model.py`` writes ``model.onnx``, ``tokenizer.json`` and
``version.json`` to ``GUARD_MODEL_DIR``; the repository stores no weights. A
text longer than one 512-token window is split into overlapping windows and
its score is the highest malicious probability among them. At most
``MAX_WINDOWS`` windows are scored per text, so a very long text is scored on
its first windows only; the rules still read all of it.

Unit tests use a fake classifier; ``load_classifier`` returns None when the
directory holds no model, which makes every screen ``unavailable``.
"""

from collections.abc import Sequence
import json
import logging
from pathlib import Path
from typing import Protocol

import numpy as np

logger = logging.getLogger(__name__)

MAX_TOKENS = 512
# Consecutive windows share this many tokens, so a phrase on a window edge is read whole by one of them.
OVERLAP = 64
MAX_WINDOWS = 8
BATCH_WINDOWS = 16
MODEL_FILE = "model.onnx"
TOKENIZER_FILE = "tokenizer.json"
VERSION_FILE = "version.json"


class Classifier(Protocol):
    version: str

    def scores(self, texts: Sequence[str]) -> list[float]:
        """The malicious probability of each text, from 0 to 1, in order."""


def windows(ids: Sequence[int], body: int, overlap: int = OVERLAP, limit: int = MAX_WINDOWS) -> list[list[int]]:
    """Overlapping slices of ``ids`` of at most ``body`` tokens, at most ``limit`` of them; one empty slice for no ids.

    The overlap is at most half a window, so every window moves on by at least half its size.
    """
    if not ids:
        return [[]]
    overlap = min(overlap, body // 2)
    step = body - overlap
    starts = range(0, max(len(ids) - overlap, 1), step)
    return [list(ids[start:start + body]) for start in starts][:limit]


def softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - logits.max(axis=-1, keepdims=True)
    exp = np.exp(shifted)
    return exp / exp.sum(axis=-1, keepdims=True)


class OnnxClassifier:
    """Prompt Guard as exported by the fetch job, run on CPU with ONNX Runtime."""

    def __init__(self, session, tokenizer, *, version: str, malicious_index: int, max_tokens: int = MAX_TOKENS):
        self._session = session
        self._tokenizer = tokenizer
        self._inputs = {item.name for item in session.get_inputs()}
        self.version = version
        self._malicious = malicious_index
        self._cls = tokenizer.token_to_id("[CLS]")
        self._sep = tokenizer.token_to_id("[SEP]")
        self._pad = tokenizer.token_to_id("[PAD]") or 0
        self._body = max_tokens - 2

    @classmethod
    def load(cls, model_dir: Path) -> "OnnxClassifier":
        import onnxruntime
        from tokenizers import Tokenizer

        meta = json.loads((model_dir / VERSION_FILE).read_text(encoding="utf-8"))
        options = onnxruntime.SessionOptions()
        options.log_severity_level = 3
        session = onnxruntime.InferenceSession(
            str(model_dir / MODEL_FILE), sess_options=options, providers=["CPUExecutionProvider"],
        )
        tokenizer = Tokenizer.from_file(str(model_dir / TOKENIZER_FILE))
        tokenizer.no_truncation()
        tokenizer.no_padding()
        return cls(
            session, tokenizer, version=str(meta["version"]), malicious_index=int(meta["malicious_index"]),
            max_tokens=int(meta.get("max_tokens", MAX_TOKENS)),
        )

    def scores(self, texts: Sequence[str]) -> list[float]:
        owners: list[int] = []
        rows: list[list[int]] = []
        for number, encoding in enumerate(self._tokenizer.encode_batch(list(texts), add_special_tokens=False)):
            for window in windows(encoding.ids, self._body):
                owners.append(number)
                rows.append([self._cls, *window, self._sep])
        best = [0.0] * len(texts)
        for start in range(0, len(rows), BATCH_WINDOWS):
            batch = rows[start:start + BATCH_WINDOWS]
            for owner, score in zip(owners[start:start + BATCH_WINDOWS], self._run(batch), strict=True):
                best[owner] = max(best[owner], score)
        return best

    def _run(self, rows: list[list[int]]) -> list[float]:
        width = max(len(row) for row in rows)
        ids = np.full((len(rows), width), self._pad, dtype=np.int64)
        mask = np.zeros((len(rows), width), dtype=np.int64)
        for index, row in enumerate(rows):
            ids[index, :len(row)] = row
            mask[index, :len(row)] = 1
        feed = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self._inputs:
            feed["token_type_ids"] = np.zeros_like(ids)
        (logits,) = self._session.run(["logits"], {name: value for name, value in feed.items() if name in self._inputs})
        return [float(value) for value in softmax(logits)[:, self._malicious]]


def load_classifier(model_dir: Path) -> Classifier | None:
    """The classifier in ``model_dir``, or None when it is missing or cannot be loaded."""
    if not (model_dir / MODEL_FILE).is_file():
        logger.warning("no screening classifier in %s; screening is unavailable", model_dir)
        return None
    try:
        return OnnxClassifier.load(model_dir)
    except Exception:  # noqa: BLE001 - a broken model leaves screening unavailable, which fails closed
        logger.exception("cannot load the screening classifier from %s", model_dir)
        return None
