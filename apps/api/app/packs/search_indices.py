"""OpenSearch index definitions, documents and queries for a compiled pack.

Each pack owns six logical indices. A compile writes generation ``N`` of every
index under the physical name ``<pack>_<index>_v<N>``; retrieval reads the
alias ``<pack>_<index>``, so packs never overwrite each other and a new
generation goes live with one atomic alias move.

Every document is ``{id, type, pack, allowed_roles, title, text, ...}``. Text
fields fold case and diacritics, so "doanh thu" also matches "Doanh Thu" and
"doanh thú". Semantic indices carry an ``embedding`` vector searched together
with BM25 through the hybrid pipeline; ``column_values`` is lexical only, with
fuzzy and trigram matching for misspelled values.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
import hashlib
import re

from app.llm.embeddings import EmbeddingClient
from app.packs.models import Pack
from app.search.opensearch import OpenSearch

INDEX_NAMES = ("glossary_terms", "metrics", "datasets", "column_values", "examples", "kb_docs")
LEXICAL_INDICES = frozenset({"column_values"})
HYBRID_PIPELINE = "hybrid_search"
HYBRID_WEIGHTS = (0.5, 0.5)  # BM25, kNN

HYBRID_PIPELINE_BODY = {
    "description": "Normalize BM25 and kNN scores, then combine them.",
    "phase_results_processors": [
        {
            "normalization-processor": {
                "normalization": {"technique": "min_max"},
                "combination": {"technique": "arithmetic_mean", "parameters": {"weights": list(HYBRID_WEIGHTS)}},
            }
        }
    ],
}

_ANALYSIS = {
    "filter": {"trigram": {"type": "ngram", "min_gram": 3, "max_gram": 3}},
    "analyzer": {
        "folded": {"type": "custom", "tokenizer": "standard", "filter": ["lowercase", "asciifolding"]},
        "folded_trigram": {"type": "custom", "tokenizer": "standard", "filter": ["lowercase", "asciifolding", "trigram"]},
    },
}


def alias_name(pack: str, index: str) -> str:
    return f"{pack}_{index}"


def physical_name(pack: str, index: str, generation: int) -> str:
    return f"{pack}_{index}_v{generation}"


def generation_of(pack: str, name: str) -> tuple[str, int] | None:
    """Return ``(index, generation)`` when ``name`` is a physical index of ``pack``."""
    pattern = rf"{re.escape(pack)}_({'|'.join(INDEX_NAMES)})_v(\d+)"
    match = re.fullmatch(pattern, name)
    return (match.group(1), int(match.group(2))) if match else None


def index_body(index: str, dimensions: int) -> dict:
    """Settings and mappings for one physical index."""
    properties: dict = {
        "id": {"type": "keyword"},
        "type": {"type": "keyword"},
        "pack": {"type": "keyword"},
        "allowed_roles": {"type": "keyword"},
        "dataset": {"type": "keyword"},
        "title": {"type": "text", "analyzer": "folded"},
        "text": {"type": "text", "analyzer": "folded"},
        "payload": {"type": "object", "enabled": False},
    }
    settings: dict = {"number_of_shards": 1, "number_of_replicas": 0, "analysis": _ANALYSIS}
    if index in LEXICAL_INDICES:
        properties["column"] = {"type": "keyword"}
        properties["title"]["fields"] = {"trigram": {"type": "text", "analyzer": "folded_trigram"}}
    else:
        settings["knn"] = True
        properties["embedding"] = {
            "type": "knn_vector",
            "dimension": dimensions,
            "method": {"name": "hnsw", "engine": "lucene", "space_type": "cosinesimil"},
        }
    return {"settings": {"index": settings}, "mappings": {"dynamic": "strict", "properties": properties}}


@dataclass(frozen=True)
class ColumnValue:
    dataset: str
    column: str
    value: str
    count: int


class _Roles:
    """Roles allowed to see each dataset and column, from policies.yaml grants."""

    def __init__(self, pack: Pack):
        self.all = sorted(role.id for role in pack.policies.roles)
        self.datasets: dict[str, set[str]] = {}
        self.columns: dict[tuple[str, str], set[str]] = {}
        for role in pack.policies.roles:
            for grant in role.datasets:
                self.datasets.setdefault(grant.dataset, set()).add(role.id)
                for column in grant.columns:
                    self.columns.setdefault((grant.dataset, column), set()).add(role.id)

    def dataset(self, dataset: str) -> list[str]:
        return sorted(self.datasets.get(dataset, set()))

    def column(self, dataset: str, column: str) -> list[str]:
        return sorted(self.columns.get((dataset, column), set()))

    def every(self, datasets: Iterable[str]) -> list[str]:
        """Roles granted every one of ``datasets``."""
        allowed = set(self.all)
        for dataset in datasets:
            allowed &= self.datasets.get(dataset, set())
        return sorted(allowed)


def _document(pack: Pack, doc_type: str, doc_id: str, roles: list[str], title: str, text: str, **extra) -> dict:
    return {"id": doc_id, "type": doc_type, "pack": pack.name, "allowed_roles": roles, "title": title, "text": text, **extra}


def build_documents(pack: Pack, column_values: Sequence[ColumnValue]) -> dict[str, list[dict]]:
    """Build the documents of all six indices from an approved-only pack.

    Documents of semantic indices carry an ``embedding_text``; the compiler
    replaces it with the ``embedding`` vector before indexing.
    """
    roles = _Roles(pack)
    metric_dataset = {metric.id: metric.dataset for metric in pack.metrics.metrics}
    documents: dict[str, list[dict]] = {name: [] for name in INDEX_NAMES}

    for term in pack.glossary.terms:
        allowed: set[str] = set()
        for target in term.targets:
            if target.metric is not None:
                allowed.update(roles.dataset(metric_dataset[target.metric]))
            elif target.dataset is not None and target.column is not None:
                allowed.update(roles.column(target.dataset, target.column))
        aliases = [*term.aliases.vi, *term.aliases.en]
        documents["glossary_terms"].append(_document(
            pack, "glossary_term", term.id, sorted(allowed), " | ".join([term.term, *aliases]), term.definition,
            payload={"term": term.term, "aliases": term.aliases.model_dump(), "targets": [
                target.model_dump(exclude_none=True) for target in term.targets
            ]},
            embedding_text=f"{term.term}. {', '.join(aliases)}. {term.definition}",
        ))

    for metric in pack.metrics.metrics:
        documents["metrics"].append(_document(
            pack, "metric", metric.id, roles.dataset(metric.dataset), f"{metric.name} | {metric.id}", metric.description,
            dataset=metric.dataset,
            payload={"name": metric.name, "unit": metric.unit, "grain": metric.grain, "sql_expr": metric.sql_expr},
            embedding_text=f"{metric.name}. {metric.description}",
        ))

    for dataset in pack.datasets.datasets:
        documents["datasets"].append(_document(
            pack, "dataset", dataset.id, roles.dataset(dataset.id), dataset.id, f"{dataset.description} Grain: {dataset.grain}.",
            dataset=dataset.id,
            payload={"grain": dataset.grain, "time_column": dataset.time_column},
            embedding_text=f"{dataset.id}: {dataset.description} Grain: {dataset.grain}.",
        ))
        for column in dataset.columns:
            documents["datasets"].append(_document(
                pack, "column", f"{dataset.id}.{column.name}", roles.column(dataset.id, column.name), column.name,
                column.description, dataset=dataset.id,
                payload={"column": column.name, "type": column.type, "role": column.role},
                embedding_text=f"{column.name} ({dataset.id}): {column.description}",
            ))

    for item in column_values:
        digest = hashlib.sha1(item.value.encode(), usedforsecurity=False).hexdigest()[:16]
        documents["column_values"].append(_document(
            pack, "column_value", f"{item.dataset}.{item.column}.{digest}", roles.column(item.dataset, item.column),
            item.value, f"{item.column} {item.dataset}", dataset=item.dataset, column=item.column,
            payload={"column": item.column, "value": item.value, "count": item.count},
        ))

    for example in pack.examples.examples:
        documents["examples"].append(_document(
            pack, "example", example.id, roles.every(example.datasets), example.question, example.question,
            payload={"sql": example.sql, "language": example.language, "datasets": example.datasets,
                     "metrics": example.metrics},
            embedding_text=example.question,
        ))
    return documents


def _role_filter(roles: Sequence[str]) -> dict:
    return {"terms": {"allowed_roles": list(roles)}}


def hybrid_query(text: str, vector: Sequence[float], roles: Sequence[str], size: int) -> dict:
    """BM25 and kNN subqueries, both filtered by role, for the hybrid pipeline."""
    return {
        "size": size,
        "_source": {"excludes": ["embedding"]},
        "query": {
            "hybrid": {
                "queries": [
                    {"bool": {
                        "must": {"multi_match": {"query": text, "fields": ["title^2", "text"]}},
                        "filter": [_role_filter(roles)],
                    }},
                    {"knn": {"embedding": {"vector": list(vector), "k": size, "filter": _role_filter(roles)}}},
                ]
            }
        },
    }


def value_query(text: str, roles: Sequence[str], size: int) -> dict:
    """Fuzzy and trigram match of a column value, filtered by role."""
    return {
        "size": size,
        "query": {
            "bool": {
                "should": [
                    {"match": {"title": {"query": text, "fuzziness": "AUTO", "boost": 2}}},
                    {"match": {"title.trigram": text}},
                ],
                "minimum_should_match": 1,
                "filter": [_role_filter(roles)],
            }
        },
    }


def search_pack(
    search: OpenSearch, embeddings: EmbeddingClient, pack: str, text: str, roles: Sequence[str], size: int
) -> dict[str, list[dict]]:
    """Search the live aliases of all six indices of ``pack`` for ``text``."""
    vector = embeddings.embed([text])[0]
    results: dict[str, list[dict]] = {}
    for index in INDEX_NAMES:
        alias = alias_name(pack, index)
        if index in LEXICAL_INDICES:
            results[index] = search.search(alias, value_query(text, roles, size))
        else:
            results[index] = search.search(alias, hybrid_query(text, vector, roles, size), pipeline=HYBRID_PIPELINE)
    return results
