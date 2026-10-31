"""In-memory stand-ins for ClickHouse, OpenSearch and the embedding alias.

They record every call so tests can assert ordering, and each can be told to
fail at a chosen point.
"""

from collections.abc import Iterable, Sequence
from datetime import date
import fnmatch
import re

from app.search.opensearch import SearchError


class FakeWarehouse:
    """Answers the compiler's queries from a table -> columns mapping.

    ``coverage`` maps a table to ``(rows, min_date, max_date)``; ``values`` maps
    ``(table, column)`` to ``[(value, count)]``; ``failures`` maps a substring of
    the SQL to the error raised for any query containing it.
    """

    def __init__(
        self,
        tables: dict[str, set[str]],
        coverage: dict[str, tuple[int, date, date]] | None = None,
        values: dict[tuple[str, str], list[tuple[str, int]]] | None = None,
        failures: dict[str, str] | None = None,
    ):
        self.tables = tables
        self.coverage = coverage or {}
        self.values = values or {}
        self.failures = failures or {}
        self.queries: list[tuple[str, dict | None]] = []

    def query(self, sql: str, settings: dict | None = None) -> list[tuple]:
        self.queries.append((sql, settings))
        for fragment, message in self.failures.items():
            if fragment in sql:
                raise RuntimeError(message)
        if "system.columns" in sql:
            return [(table, column) for table, columns in self.tables.items() for column in sorted(columns)]
        table = re.search(r"FROM `marts`\.`(\w+)`", sql).group(1)
        if sql.startswith("SELECT count(), min("):
            return [self.coverage.get(table, (0, date(1970, 1, 1), date(1970, 1, 1)))]
        if "toString(" in sql:
            column = re.search(r"toString\(`(\w+)`\)", sql).group(1)
            return self.values.get((table, column), [])
        return [(1,)]


class FakeEmbeddings:
    """Deterministic vectors; ``fail_after`` raises once that many texts were embedded."""

    def __init__(self, dimensions: int = 4, fail_after: int | None = None):
        self.dimensions = dimensions
        self.fail_after = fail_after
        self.calls: list[list[str]] = []

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        embedded = sum(len(call) for call in self.calls)
        if self.fail_after is not None and embedded + len(texts) > self.fail_after:
            raise RuntimeError("embedding service unavailable")
        self.calls.append(list(texts))
        return [[float(len(text) % 7), 1.0, 0.0, 0.5][: self.dimensions] for text in texts]


class FakeSearch:
    """In-memory OpenSearch: indices, documents, aliases and a call log.

    ``fail_bulk_into`` makes bulk indexing into any index whose name contains
    that substring fail; ``search_results`` maps an alias to the hits returned.
    """

    def __init__(self, fail_bulk_into: str | None = None, search_results: dict[str, list[dict]] | None = None):
        self.indices: dict[str, dict] = {}
        self.documents: dict[str, list[dict]] = {}
        self.aliases: dict[str, str] = {}
        self.pipelines: dict[str, dict] = {}
        self.alias_updates: list[list[dict]] = []
        self.searches: list[tuple[str, dict, str | None]] = []
        self.fail_bulk_into = fail_bulk_into
        self.search_results = search_results or {}

    def put_search_pipeline(self, name: str, body: dict) -> None:
        self.pipelines[name] = body

    def create_index(self, name: str, body: dict) -> None:
        if name in self.indices:
            raise SearchError(f"index {name} already exists")
        self.indices[name] = body
        self.documents[name] = []

    def delete_index(self, name: str) -> None:
        self.indices.pop(name, None)
        self.documents.pop(name, None)
        self.aliases = {alias: index for alias, index in self.aliases.items() if index != name}

    def list_indices(self, pattern: str) -> list[str]:
        return sorted(name for name in self.indices if fnmatch.fnmatchcase(name, pattern))

    def alias_targets(self, pattern: str) -> dict[str, list[str]]:
        return {alias: [index] for alias, index in self.aliases.items() if fnmatch.fnmatchcase(alias, pattern)}

    def update_aliases(self, actions: list[dict]) -> None:
        self.alias_updates.append(actions)
        for action in actions:
            if "remove" in action:
                self.aliases.pop(action["remove"]["alias"], None)
            else:
                self.aliases[action["add"]["alias"]] = action["add"]["index"]

    def bulk_index(self, index: str, documents: Iterable[dict]) -> int:
        if self.fail_bulk_into and self.fail_bulk_into in index:
            raise SearchError(f"bulk indexing into {index} failed")
        documents = list(documents)
        self.documents[index].extend(documents)
        return len(documents)

    def refresh(self, index: str) -> None:
        pass

    def count(self, index: str) -> int:
        return len(self.documents[index])

    def search(self, index: str, body: dict, pipeline: str | None = None) -> list[dict]:
        self.searches.append((index, body, pipeline))
        return self.search_results.get(index, [])
