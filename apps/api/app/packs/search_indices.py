"""Qdrant collections, documents and points for a compiled pack (DECISIONS §5).

Each pack owns six logical collections. A compile writes generation ``N`` of
every collection under the name ``<pack>_<index>_v<N>``; retrieval reads the
alias ``<pack>_<index>``, so packs never overwrite each other and a new
generation goes live with one atomic alias move.

Every document is ``{id, type, pack, allowed_roles, title, text, ...}`` and
becomes one point whose payload is the document. A point carries a dense
``embed`` vector and a BM25 sparse vector of its title (counted twice) and
text; column values also carry character trigrams, so a misspelled value
still matches. ``allowed_roles`` and ``type`` have payload indexes.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
import hashlib
import re

from app.llm.embeddings import EmbeddingClient
from app.packs.models import Pack
from app.search import sparse
from app.search.client import BM25, DENSE, TRIGRAM, point_id, uses_trigrams

INDEX_NAMES = ("glossary_terms", "metrics", "datasets", "column_values", "examples", "kb_docs")


def alias_name(pack: str, index: str) -> str:
    return f"{pack}_{index}"


def physical_name(pack: str, index: str, generation: int) -> str:
    return f"{pack}_{index}_v{generation}"


def generation_of(pack: str, name: str) -> tuple[str, int] | None:
    """Return ``(index, generation)`` when ``name`` is a physical index of ``pack``."""
    pattern = rf"{re.escape(pack)}_({'|'.join(INDEX_NAMES)})_v(\d+)"
    match = re.fullmatch(pattern, name)
    return (match.group(1), int(match.group(2))) if match else None


@dataclass(frozen=True)
class ColumnValue:
    dataset: str
    column: str
    value: str
    count: int


class PackRoles:
    """Roles allowed to see each dataset, column and metric, from policies.yaml grants.

    An aggregate-only grant shows its grouped columns and listed metrics only,
    and no examples, whose SQL reads the table that the role cannot read.
    """

    def __init__(self, pack: Pack):
        self.all = sorted(role.id for role in pack.policies.roles)
        self.datasets: dict[str, set[str]] = {}
        self.table_readers: dict[str, set[str]] = {}
        self.columns: dict[tuple[str, str], set[str]] = {}
        self.aggregate_metrics: dict[str, set[str]] = {}
        for role in pack.policies.roles:
            for grant in role.datasets:
                self.datasets.setdefault(grant.dataset, set()).add(role.id)
                for column in grant.columns:
                    self.columns.setdefault((grant.dataset, column), set()).add(role.id)
                if grant.aggregate_only is None:
                    self.table_readers.setdefault(grant.dataset, set()).add(role.id)
                else:
                    for metric in grant.aggregate_only.metrics:
                        self.aggregate_metrics.setdefault(metric, set()).add(role.id)

    def dataset(self, dataset: str) -> list[str]:
        return sorted(self.datasets.get(dataset, set()))

    def column(self, dataset: str, column: str) -> list[str]:
        return sorted(self.columns.get((dataset, column), set()))

    def metric(self, metric: str, dataset: str) -> list[str]:
        return sorted(self.table_readers.get(dataset, set()) | self.aggregate_metrics.get(metric, set()))

    def every(self, datasets: Iterable[str]) -> list[str]:
        """Roles that read every one of ``datasets`` as a table."""
        allowed = set(self.all)
        for dataset in datasets:
            allowed &= self.table_readers.get(dataset, set())
        return sorted(allowed)


def value_id(dataset: str, column: str, value: str) -> str:
    """The document id of one column value."""
    digest = hashlib.sha1(value.encode(), usedforsecurity=False).hexdigest()[:16]
    return f"{dataset}.{column}.{digest}"


def source_id(source: str) -> tuple[str, str]:
    """``(index, document id)`` of an eval label ``<index>:<key>``; a column value's key is ``dataset.column=value``."""
    index, _, key = source.partition(":")
    if index == "column_values":
        column, _, value = key.partition("=")
        dataset, _, name = column.partition(".")
        return index, value_id(dataset, name, value)
    return index, key


def _document(pack: Pack, doc_type: str, doc_id: str, roles: list[str], title: str, text: str, **extra) -> dict:
    return {"id": doc_id, "type": doc_type, "pack": pack.name, "allowed_roles": roles, "title": title, "text": text, **extra}


def build_documents(pack: Pack, column_values: Sequence[ColumnValue]) -> dict[str, list[dict]]:
    """Build the documents of all six indices from an approved-only pack.

    Every document carries an ``embedding_text``, which the compiler embeds
    into the point's dense vector and leaves out of the payload.
    """
    roles = PackRoles(pack)
    metric_dataset = {metric.id: metric.dataset for metric in pack.metrics.metrics}
    documents: dict[str, list[dict]] = {name: [] for name in INDEX_NAMES}

    for term in pack.glossary.terms:
        allowed: set[str] = set()
        for target in term.targets:
            if target.metric is not None:
                allowed.update(roles.metric(target.metric, metric_dataset[target.metric]))
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
            pack, "metric", metric.id, roles.metric(metric.id, metric.dataset), f"{metric.name} | {metric.id}", metric.description,
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
        documents["column_values"].append(_document(
            pack, "column_value", value_id(item.dataset, item.column, item.value), roles.column(item.dataset, item.column),
            item.value, f"{item.column} {item.dataset}", dataset=item.dataset, column=item.column,
            payload={"column": item.column, "value": item.value, "count": item.count},
            embedding_text=item.value,
        ))

    for example in pack.examples.examples:
        documents["examples"].append(_document(
            pack, "example", example.id, roles.every(example.datasets), example.question, example.question,
            payload={"sql": example.sql, "language": example.language, "datasets": example.datasets,
                     "metrics": example.metrics},
            embedding_text=example.question,
        ))
    return documents


def bm25_tokens(document: dict) -> list[str]:
    """The keyword terms of a document: its title counts twice, so a match on the name ranks first."""
    title = str(document.get("title", ""))
    return sparse.terms(f"{title} {title} {document.get('text', '')}")


def points(name: str, documents: Sequence[dict], vectors: Sequence[Sequence[float]]) -> list[dict]:
    """The Qdrant points of one collection's documents, with their dense vectors in order."""
    tokens = [bm25_tokens(document) for document in documents]
    average = sparse.average_length(tokens)
    result = []
    for document, words, vector in zip(documents, tokens, vectors, strict=True):
        payload = {key: value for key, value in document.items() if key != "embedding_text"}
        named = {DENSE: list(vector), BM25: sparse.document_vector(words, average)}
        if uses_trigrams(name):
            named[TRIGRAM] = sparse.document_vector(sparse.trigrams(str(document.get("title", ""))), 1.0)
        result.append({"id": point_id(document["id"]), "vector": named, "payload": payload})
    return result


def search_pack(search, embeddings: EmbeddingClient, pack: str, text: str, roles: Sequence[str], size: int) -> dict[str, list[dict]]:
    """Search the live aliases of all six collections of ``pack`` for ``text`` through ``search.query``."""
    vector = embeddings.embed([text])[0]
    return {index: search.query(alias_name(pack, index), text, vector, roles, size) for index in INDEX_NAMES}
