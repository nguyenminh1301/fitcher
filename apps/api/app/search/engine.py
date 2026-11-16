"""The search interface of the pack compiler, company documents and the agent (DECISIONS §5).

A pack owns one logical collection per search index, named
``<pack>_<index>``. A compile writes generation ``N`` of each collection and
then makes that generation live for all of them at once, so a reader never
sees a mixed generation; retrieval always reads the live generation.

A point is engine-neutral: ``{id, vector, payload}`` where ``vector`` holds
the dense vector under ``DENSE``, the BM25 term weights under ``BM25`` and,
for column values, the character-trigram weights under ``TRIGRAM``; each
sparse vector is ``{indices, values}`` from ``app.search.sparse``. Every
payload carries ``allowed_roles``; a ``kb_docs`` chunk also carries its
``document_id``.

``query`` is the hybrid search: the dense, BM25 and (for column values)
trigram candidates readable by any of ``roles``, fused with RRF. Hits are
``{id, score, source}`` with the pack document id and its payload.

Callers import this module only; ``open_search`` returns the configured engine.
"""

from collections.abc import Iterable, Mapping, Sequence
from typing import TYPE_CHECKING, Protocol
import uuid

if TYPE_CHECKING:
    from app.config import Settings

DENSE = "dense"
BM25 = "bm25"
TRIGRAM = "trigram"
# Each ranked list keeps this many candidates per requested hit before fusion.
PREFETCH_FACTOR = 4
# Point ids are UUIDs derived from the pack document id, which stays in the payload.
_POINT_NAMESPACE = uuid.UUID("0b8f5a52-7c1d-4b4e-9a3f-6f1d2c9e8a10")


class SearchError(RuntimeError):
    """A search engine request failed."""


def point_id(document_id: str) -> str:
    return str(uuid.uuid5(_POINT_NAMESPACE, document_id))


def prefetch_limit(size: int) -> int:
    """Candidates each ranked list keeps before RRF fusion for ``size`` hits."""
    return max(size * PREFETCH_FACTOR, 20)


def uses_trigrams(collection: str) -> bool:
    """Column value collections also carry character trigrams."""
    return "_column_values" in collection


class SearchEngine(Protocol):
    def generations(self, collection: str) -> list[int]:
        """The generations of ``collection`` that exist, live or not, in ascending order."""

    def live(self) -> dict[str, int]:
        """The live generation of every collection that has one."""

    def create(self, collection: str, generation: int, dimensions: int) -> None:
        """Create an empty generation of ``collection`` for vectors of ``dimensions``."""

    def drop(self, collection: str, generation: int) -> None:
        """Delete one generation; a missing one is not an error."""

    def write(self, collection: str, points: Iterable[dict], generation: int | None = None) -> int:
        """Write points into ``generation``, or into the live one when it is ``None``; return how many."""

    def size(self, collection: str, generation: int) -> int:
        """The number of points in one generation."""

    def switch_live(self, generations: Mapping[str, int]) -> None:
        """Make each collection's given generation live, all in one atomic step."""

    def live_points(self, collection: str, document_id: str | None = None, with_vectors: bool = False) -> list[dict]:
        """The live points, of one company document or of all, as ``{id, payload}`` and ``vector`` when asked."""

    def delete_document(self, collection: str, document_id: str) -> None:
        """Delete every live point of one company document."""

    def set_document_roles(self, collection: str, document_id: str, roles: Sequence[str]) -> None:
        """Replace ``allowed_roles`` on every live point of one company document."""

    def query(self, collection: str, text: str, vector: Sequence[float], roles: Sequence[str], size: int) -> list[dict]:
        """Hybrid keyword and semantic hits of the live ``collection`` readable by ``roles``."""


def open_search(settings: "Settings") -> SearchEngine:
    """The configured search engine: ``SEARCH_ENGINE`` is ``qdrant`` or ``clickhouse``."""
    # Imported here so this module stays free of either engine's dependencies.
    if settings.search_engine == "clickhouse":
        from app.search.clickhouse_index import ClickHouseSearch, search_client  # noqa: PLC0415

        return ClickHouseSearch(search_client())
    from app.search.client import QdrantSearch  # noqa: PLC0415

    return QdrantSearch(settings.qdrant_url)
