"""Qdrant REST client for the pack's search collections (DECISIONS §5).

Only the calls the pack compiler, retrieval and the measurement need are
wrapped, over httpx like the other clients. Each failed call raises
``SearchError`` with the HTTP status and Qdrant's error message.

``query`` is the agent's hybrid search: one prefetch on the dense ``embed``
vector, one on the BM25 sparse vector and, for column values, one on the
character-trigram vector, each filtered by ``allowed_roles``, fused with RRF
on the server. Hits are ``{id, score, source}`` with the pack document id and
its payload.
"""

from collections.abc import Iterable, Sequence
from typing import Any
import uuid

import httpx

from app.search import sparse

TIMEOUT_SECONDS = 60
UPSERT_BATCH = 256
# Each prefetch keeps this many candidates per requested hit before fusion.
PREFETCH_FACTOR = 4
DENSE = "dense"
BM25 = "bm25"
TRIGRAM = "trigram"
# Point ids are UUIDs derived from the pack document id, which stays in the payload.
_POINT_NAMESPACE = uuid.UUID("0b8f5a52-7c1d-4b4e-9a3f-6f1d2c9e8a10")


class SearchError(RuntimeError):
    """A Qdrant request failed."""


def point_id(document_id: str) -> str:
    return str(uuid.uuid5(_POINT_NAMESPACE, document_id))


def role_filter(roles: Sequence[str]) -> dict:
    return {"must": [{"key": "allowed_roles", "match": {"any": list(roles)}}]}


def document_filter(document_id: str) -> dict:
    """Every ``kb_docs`` chunk of one company document."""
    return {"must": [{"key": "document_id", "match": {"value": document_id}}]}


def uses_trigrams(name: str) -> bool:
    """Column value collections, and their aliases, also carry character trigrams."""
    return "_column_values" in name


def hybrid_request(alias: str, text: str, vector: Sequence[float], roles: Sequence[str], size: int) -> dict:
    """The query body: role-filtered prefetches on every vector of the collection, fused with RRF."""
    limit = max(size * PREFETCH_FACTOR, 20)
    flt = role_filter(roles)
    prefetch: list[dict] = [{"query": list(vector), "using": DENSE, "filter": flt, "limit": limit}]
    words = sparse.query_vector(sparse.terms(text))
    if words["indices"]:
        prefetch.append({"query": words, "using": BM25, "filter": flt, "limit": limit})
    grams = sparse.query_vector(sparse.trigrams(text))
    if uses_trigrams(alias) and grams["indices"]:
        prefetch.append({"query": grams, "using": TRIGRAM, "filter": flt, "limit": limit})
    return {"prefetch": prefetch, "query": {"fusion": "rrf"}, "limit": size, "with_payload": True}


class QdrantSearch:
    def __init__(self, base_url: str, http: httpx.Client | None = None):
        self._base = base_url.rstrip("/")
        self._http = http or httpx.Client(timeout=TIMEOUT_SECONDS)

    def _request(self, method: str, path: str, *, ok_missing: bool = False, **kwargs: Any) -> Any:
        try:
            response = self._http.request(method, f"{self._base}{path}", **kwargs)
        except httpx.HTTPError as error:
            raise SearchError(f"{method} {path} failed: {type(error).__name__}") from error
        if ok_missing and response.status_code == 404:
            return None
        if response.status_code >= 300:
            raise SearchError(f"{method} {path} returned HTTP {response.status_code}: {_reason(response)}")
        return response.json().get("result") if response.content else None

    # collections

    def create_collection(self, name: str, dimensions: int) -> None:
        sparse_vectors = {BM25: {"modifier": "idf"}}
        if uses_trigrams(name):
            sparse_vectors[TRIGRAM] = {"modifier": "idf"}
        self._request("PUT", f"/collections/{name}", json={
            "vectors": {DENSE: {"size": dimensions, "distance": "Cosine"}}, "sparse_vectors": sparse_vectors,
        })
        for field in ("allowed_roles", "type"):
            self._request("PUT", f"/collections/{name}/index", params={"wait": "true"},
                          json={"field_name": field, "field_schema": "keyword"})

    def delete_collection(self, name: str) -> None:
        self._request("DELETE", f"/collections/{name}", ok_missing=True)

    def list_collections(self) -> list[str]:
        result = self._request("GET", "/collections") or {}
        return sorted(item["name"] for item in result.get("collections", []))

    def alias_targets(self) -> dict[str, str]:
        result = self._request("GET", "/aliases") or {}
        return {item["alias_name"]: item["collection_name"] for item in result.get("aliases", [])}

    def update_aliases(self, actions: list[dict]) -> None:
        """Apply every alias action in one atomic request."""
        self._request("POST", "/collections/aliases", json={"actions": actions})

    def upsert(self, name: str, points: Iterable[dict]) -> int:
        """Write points (``{id, vector, payload}``) in batches and wait until they are searchable."""
        count = 0
        batch: list[dict] = []
        for point in points:
            batch.append(point)
            if len(batch) == UPSERT_BATCH:
                count += self._upsert(name, batch)
                batch = []
        if batch:
            count += self._upsert(name, batch)
        return count

    def _upsert(self, name: str, points: list[dict]) -> int:
        self._request("PUT", f"/collections/{name}/points", params={"wait": "true"}, json={"points": points})
        return len(points)

    def scroll(self, name: str, flt: dict | None = None, with_vectors: bool = False) -> list[dict]:
        """Every point of ``name`` (a collection or alias) matching ``flt``, page by page."""
        points: list[dict] = []
        offset = None
        while True:
            body: dict = {"limit": UPSERT_BATCH, "with_payload": True, "with_vector": with_vectors}
            if flt is not None:
                body["filter"] = flt
            if offset is not None:
                body["offset"] = offset
            result = self._request("POST", f"/collections/{name}/points/scroll", json=body) or {}
            points.extend(result.get("points", []))
            offset = result.get("next_page_offset")
            if offset is None:
                return points

    def delete_points(self, name: str, flt: dict) -> None:
        self._request("POST", f"/collections/{name}/points/delete", params={"wait": "true"}, json={"filter": flt})

    def set_payload(self, name: str, payload: dict, flt: dict) -> None:
        self._request("POST", f"/collections/{name}/points/payload", params={"wait": "true"},
                      json={"payload": payload, "filter": flt})

    def count(self, name: str) -> int:
        return self._request("POST", f"/collections/{name}/points/count", json={"exact": True})["count"]

    # search

    def query(self, alias: str, text: str, vector: Sequence[float], roles: Sequence[str], size: int) -> list[dict]:
        result = self._request("POST", f"/collections/{alias}/points/query", json=hybrid_request(alias, text, vector, roles, size))
        return [
            {"id": point["payload"]["id"], "score": point["score"], "source": point["payload"]}
            for point in (result or {}).get("points", [])
        ]


def _reason(response: httpx.Response) -> str:
    try:
        status = response.json().get("status")
    except ValueError:
        return response.text[:200]
    if isinstance(status, dict):
        return str(status.get("error"))[:300]
    return str(status)[:200]
