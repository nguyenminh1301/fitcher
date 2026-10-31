"""Minimal OpenSearch REST client for index management and search.

Only the calls the pack compiler and retrieval need are wrapped. Each failed
call raises SearchError with the HTTP status and OpenSearch's error reason.
"""

from collections.abc import Iterable
import json
from typing import Any

import httpx

TIMEOUT_SECONDS = 60
BULK_CHUNK = 500


class SearchError(RuntimeError):
    """An OpenSearch request failed."""


class OpenSearch:
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
        return response.json() if response.content else None

    def put_search_pipeline(self, name: str, body: dict) -> None:
        self._request("PUT", f"/_search/pipeline/{name}", json=body)

    def create_index(self, name: str, body: dict) -> None:
        self._request("PUT", f"/{name}", json=body)

    def delete_index(self, name: str) -> None:
        self._request("DELETE", f"/{name}", ok_missing=True)

    def list_indices(self, pattern: str) -> list[str]:
        rows = self._request("GET", f"/_cat/indices/{pattern}", params={"format": "json", "h": "index"}, ok_missing=True)
        return sorted(row["index"] for row in rows or [])

    def alias_targets(self, pattern: str) -> dict[str, list[str]]:
        """Return alias -> indices for aliases matching ``pattern``."""
        body = self._request("GET", f"/_alias/{pattern}", ok_missing=True) or {}
        targets: dict[str, list[str]] = {}
        for index, entry in body.items():
            for alias in entry.get("aliases", {}):
                targets.setdefault(alias, []).append(index)
        return targets

    def update_aliases(self, actions: list[dict]) -> None:
        """Apply every alias action in one atomic request."""
        self._request("POST", "/_aliases", json={"actions": actions})

    def bulk_index(self, index: str, documents: Iterable[dict]) -> int:
        """Index documents by their ``id`` field; return the number indexed."""
        count = 0
        batch: list[dict] = []
        for document in documents:
            batch.append(document)
            if len(batch) == BULK_CHUNK:
                count += self._bulk(index, batch)
                batch = []
        if batch:
            count += self._bulk(index, batch)
        return count

    def _bulk(self, index: str, documents: list[dict]) -> int:
        lines = []
        for document in documents:
            lines.append(json.dumps({"index": {"_index": index, "_id": document["id"]}}))
            lines.append(json.dumps(document, ensure_ascii=False))
        body = self._request(
            "POST", "/_bulk", content=("\n".join(lines) + "\n").encode(),
            headers={"Content-Type": "application/x-ndjson"},
        )
        if body.get("errors"):
            failed = next(item["index"] for item in body["items"] if "error" in item["index"])
            raise SearchError(f"bulk indexing into {index} failed for {failed['_id']}: {failed['error'].get('reason')}")
        return len(documents)

    def refresh(self, index: str) -> None:
        self._request("POST", f"/{index}/_refresh")

    def count(self, index: str) -> int:
        return self._request("GET", f"/{index}/_count")["count"]

    def search(self, index: str, body: dict, pipeline: str | None = None) -> list[dict]:
        """Return the hits as ``{id, score, source}`` dictionaries."""
        params = {"search_pipeline": pipeline} if pipeline else None
        result = self._request("POST", f"/{index}/_search", json=body, params=params)
        return [{"id": hit["_id"], "score": hit["_score"], "source": hit["_source"]} for hit in result["hits"]["hits"]]


def _reason(response: httpx.Response) -> str:
    try:
        error = response.json().get("error")
    except ValueError:
        return response.text[:200]
    if isinstance(error, dict):
        return str(error.get("reason") or error.get("type"))
    return str(error)[:200]
