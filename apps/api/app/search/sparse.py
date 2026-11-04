"""Sparse vectors for keyword search in Qdrant (DECISIONS §5).

``terms`` reads NFKC, lower-cased text as word tokens (Vietnamese syllables
are space-separated words) and keeps each token both as written and with its
diacritics removed (``đ`` becomes ``d``), so "doanh thu", "Doanh Thu" and
"doanh thú" share terms. An identifier such as ``widget_revenue`` is kept whole and
also split at its underscores.

A document vector holds each term's BM25 term-frequency part, normalised by
the document's length against the collection's average; the collection's
``idf`` modifier makes Qdrant apply the inverse document frequency at query
time. A query vector holds each of its terms once with weight 1.

Column values also get character trigrams of their folded text, so a
misspelled value ("Electornics") still shares most of its terms with the
real one.

Terms map to sparse indices by CRC-32, the same at compile and query time.
"""

from collections import Counter
from collections.abc import Iterable
import re
import unicodedata
import zlib

K1 = 1.2
B = 0.75
_WORD = re.compile(r"\w+")


def _fold(text: str) -> str:
    text = text.replace("đ", "d").replace("Đ", "D")
    return "".join(char for char in unicodedata.normalize("NFD", text) if not unicodedata.combining(char))


def terms(text: str) -> list[str]:
    """Word terms of ``text``: each token as written and folded, and an identifier's parts."""
    found: list[str] = []
    for token in _WORD.findall(unicodedata.normalize("NFKC", text).lower()):
        variants = [token, *([part for part in token.split("_") if part] if "_" in token else [])]
        for variant in variants:
            found.append(variant)
            folded = _fold(variant)
            if folded != variant:
                found.append(folded)
    return found


def trigrams(text: str) -> list[str]:
    """Character trigrams of each folded word, padded so short words and word edges count."""
    grams: list[str] = []
    for token in _WORD.findall(_fold(unicodedata.normalize("NFKC", text).lower())):
        padded = f"  {token} "
        grams.extend(f"#{padded[start:start + 3]}" for start in range(len(padded) - 2))
    return grams


def _index(term: str) -> int:
    return zlib.crc32(term.encode("utf-8"))


def _vector(weights: dict[int, float]) -> dict:
    ordered = sorted(weights.items())
    return {"indices": [index for index, _ in ordered], "values": [round(weight, 6) for _, weight in ordered]}


def document_vector(tokens: Iterable[str], average_length: float) -> dict:
    """The BM25 term-frequency part of a document's sparse vector."""
    counts = Counter(tokens)
    length = sum(counts.values())
    norm = K1 * (1 - B + B * length / max(average_length, 1.0))
    weights: dict[int, float] = {}
    for term, count in counts.items():
        index = _index(term)
        weights[index] = weights.get(index, 0.0) + count * (K1 + 1) / (count + norm)
    return _vector(weights)


def query_vector(tokens: Iterable[str]) -> dict:
    """Each distinct query term once, with weight 1."""
    return _vector({_index(term): 1.0 for term in tokens})


def average_length(documents: Iterable[list[str]]) -> float:
    lengths = [len(tokens) for tokens in documents]
    return sum(lengths) / len(lengths) if lengths else 1.0
