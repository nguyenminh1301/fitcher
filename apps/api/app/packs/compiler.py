"""Compile a Domain Pack into the artifacts the runtime reads.

The order is fixed: load and validate the pack against its schemas, its own
references and the warehouse catalog; keep approved items only; test-run every
metric; read each dataset's date coverage and the top values of indexable
columns; write a new generation of the six search indices; move all six
aliases in one request; write ``compiled.json``; and only then delete older
generations. A failure before the alias move deletes the partial generation
and leaves the live aliases untouched.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
import os
from pathlib import Path
import re
from typing import Protocol

from pydantic import BaseModel, ConfigDict
import sqlglot
from sqlglot import exp

from app.llm.embeddings import EmbeddingClient
from app.packs.loader import check_references, load_pack
from app.packs.models import Pack
from app.packs.search_indices import (
    HYBRID_PIPELINE,
    HYBRID_PIPELINE_BODY,
    INDEX_NAMES,
    LEXICAL_INDICES,
    ColumnValue,
    alias_name,
    build_documents,
    generation_of,
    index_body,
    physical_name,
)
from app.search.opensearch import OpenSearch

MARTS_DATABASE = "marts"
# readonly=2 allows only reads while still letting the query carry its own settings.
METRIC_TEST_SETTINGS = {"max_execution_time": 30, "readonly": 2}
ERROR_LIMIT = 500
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class CompileError(RuntimeError):
    """The pack cannot be compiled; the message names the failing item."""


class Warehouse(Protocol):
    """Read-only query access to ClickHouse."""

    def query(self, sql: str, settings: dict | None = None) -> Sequence[Sequence]:
        """Run one SELECT and return its rows."""


class WarehouseCatalog:
    """Catalog of the marts tables read once from ``system.columns``."""

    def __init__(self, warehouse: Warehouse):
        self._warehouse = warehouse
        self._tables: dict[str, set[str]] | None = None

    def table_columns(self, table: str) -> set[str] | None:
        if self._tables is None:
            rows = self._warehouse.query(
                f"SELECT table, name FROM system.columns WHERE database = '{MARTS_DATABASE}'"
            )
            self._tables = {}
            for table_name, column in rows:
                self._tables.setdefault(table_name, set()).add(column)
        return self._tables.get(table)


class DateCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rows: int
    min_date: str | None
    max_date: str | None


class CompiledPack(BaseModel):
    """What the runtime loads at startup: the approved pack plus warehouse facts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    pack: Pack
    generation: int
    embedding_dimensions: int
    coverage: dict[str, DateCoverage]
    compiled_at: str


@dataclass
class CompileSummary:
    pack: str
    metrics_tested: list[str]
    coverage: dict[str, DateCoverage]
    generation: int | None = None
    documents: dict[str, int] = field(default_factory=dict)


def quote(identifier: str) -> str:
    """Backtick-quote an identifier that the pack schema already restricts."""
    if not _IDENTIFIER.fullmatch(identifier):
        raise CompileError(f"unsafe identifier {identifier!r}")
    return f"`{identifier}`"


def table_ref(dataset: str) -> str:
    return f"{quote(MARTS_DATABASE)}.{quote(dataset)}"


def _first_line(error: BaseException) -> str:
    text = " ".join(str(error).split())
    return text[:ERROR_LIMIT] or type(error).__name__


def approved_pack(pack: Pack) -> Pack:
    """Drop draft items and check that approved items reference only approved items."""

    def keep(items):
        return [item for item in items if item.status == "approved"]

    approved = pack.model_copy(update={
        "business_profile": pack.business_profile.model_copy(update={"conventions": keep(pack.business_profile.conventions)}),
        "datasets": pack.datasets.model_copy(update={"datasets": keep(pack.datasets.datasets)}),
        "glossary": pack.glossary.model_copy(update={"terms": keep(pack.glossary.terms)}),
        "metrics": pack.metrics.model_copy(update={"metrics": keep(pack.metrics.metrics)}),
        "relationships": pack.relationships.model_copy(update={"relationships": keep(pack.relationships.relationships)}),
        "examples": pack.examples.model_copy(update={"examples": keep(pack.examples.examples)}),
        "policies": pack.policies.model_copy(update={"roles": keep(pack.policies.roles)}),
        "eval": pack.eval.model_copy(update={"cases": keep(pack.eval.cases)}),
    })
    issues = check_references(approved)
    if issues:
        raise CompileError(
            "approved items reference draft or missing items:\n" + "\n".join(f"  {issue}" for issue in issues)
        )
    return approved


def check_metric_expression(sql_expr: str) -> None:
    """Raise ValueError unless ``sql_expr`` parses as exactly one scalar expression."""
    # Parsing into a condition accepts expressions only: statements, a second
    # statement after ";" and trailing clauses such as FROM are parse errors.
    try:
        node = sqlglot.parse_one(sql_expr, read="clickhouse", into=exp.Condition)
    except sqlglot.errors.ParseError as error:
        raise ValueError(f"does not parse as one expression: {_first_line(error)}") from None
    if node.find(exp.Query, exp.Subquery):
        raise ValueError("must not contain a subquery")


def test_metrics(pack: Pack, warehouse: Warehouse) -> list[str]:
    """Parse and run every metric once; raise CompileError naming each failing metric."""
    failures: list[str] = []
    for metric in pack.metrics.metrics:
        try:
            check_metric_expression(metric.sql_expr)
        except ValueError as error:
            failures.append(f"metric '{metric.id}': sql_expr {error}")
            continue
        sql = f"SELECT {metric.sql_expr} FROM {table_ref(metric.dataset)} LIMIT 1"
        try:
            warehouse.query(sql, settings=METRIC_TEST_SETTINGS)
        except Exception as error:  # noqa: BLE001 - every driver error is reported with the metric id
            failures.append(f"metric '{metric.id}': ClickHouse rejected sql_expr: {_first_line(error)}")
    if failures:
        raise CompileError("metric test-run failed:\n" + "\n".join(f"  {failure}" for failure in failures))
    return [metric.id for metric in pack.metrics.metrics]


def _iso(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return None if value is None else str(value)


def read_coverage(pack: Pack, warehouse: Warehouse) -> dict[str, DateCoverage]:
    """Row count and min/max of each dataset's time column."""
    coverage: dict[str, DateCoverage] = {}
    for dataset in pack.datasets.datasets:
        column = quote(dataset.time_column)
        rows, low, high = warehouse.query(
            f"SELECT count(), min({column}), max({column}) FROM {table_ref(dataset.id)}"
        )[0]
        # min/max of an empty table return the type's default value, not NULL.
        coverage[dataset.id] = DateCoverage(
            rows=rows, min_date=_iso(low) if rows else None, max_date=_iso(high) if rows else None
        )
    return coverage


def read_column_values(pack: Pack, warehouse: Warehouse, top_k: int) -> list[ColumnValue]:
    """The ``top_k`` most frequent non-empty values of every indexable column."""
    values: list[ColumnValue] = []
    for dataset in pack.datasets.datasets:
        for column in dataset.columns:
            if not column.indexable:
                continue
            rows = warehouse.query(
                f"SELECT toString({quote(column.name)}) AS value, count() AS n FROM {table_ref(dataset.id)} "
                f"WHERE value != '' GROUP BY value ORDER BY n DESC, value LIMIT {int(top_k)}"
            )
            values.extend(ColumnValue(dataset.id, column.name, value, count) for value, count in rows)
    return values


def _embed(documents: list[dict], embeddings: EmbeddingClient) -> None:
    texts = [document.pop("embedding_text") for document in documents]
    for document, vector in zip(documents, embeddings.embed(texts), strict=True):
        document["embedding"] = vector


def _delete_quietly(search: OpenSearch, names: Sequence[str]) -> None:
    for name in names:
        try:
            search.delete_index(name)
        except Exception:  # noqa: BLE001, S110 - cleanup must not hide the original failure
            pass


def next_generation(search: OpenSearch, pack: str) -> int:
    generations = [parsed[1] for name in search.list_indices(f"{pack}_*") if (parsed := generation_of(pack, name))]
    return max(generations, default=0) + 1


def build_generation(
    search: OpenSearch, embeddings: EmbeddingClient, pack: str, documents: dict[str, list[dict]]
) -> tuple[int, dict[str, int]]:
    """Create and fill generation N+1 of every index; delete it again on any failure."""
    search.put_search_pipeline(HYBRID_PIPELINE, HYBRID_PIPELINE_BODY)
    generation = next_generation(search, pack)
    created: list[str] = []
    counts: dict[str, int] = {}
    try:
        for index in INDEX_NAMES:
            name = physical_name(pack, index, generation)
            search.create_index(name, index_body(index, embeddings.dimensions))
            created.append(name)
            docs = documents[index]
            if index not in LEXICAL_INDICES and docs:
                _embed(docs, embeddings)
            search.bulk_index(name, docs)
            search.refresh(name)
            counts[index] = search.count(name)
            if counts[index] != len(docs):
                raise CompileError(f"{name} holds {counts[index]} documents, expected {len(docs)}")
    except Exception as error:
        _delete_quietly(search, created)
        raise CompileError(f"building index generation {generation} failed: {_first_line(error)}") from error
    return generation, counts


def swap_aliases(search: OpenSearch, pack: str, generation: int) -> None:
    """Point all six aliases at ``generation`` in one atomic request."""
    current = search.alias_targets(f"{pack}_*")
    actions: list[dict] = []
    for index in INDEX_NAMES:
        alias = alias_name(pack, index)
        actions.extend({"remove": {"index": old, "alias": alias}} for old in current.get(alias, []))
        actions.append({"add": {"index": physical_name(pack, index, generation), "alias": alias}})
    search.update_aliases(actions)


def delete_older_generations(search: OpenSearch, pack: str, generation: int) -> list[str]:
    old = [
        name for name in search.list_indices(f"{pack}_*")
        if (parsed := generation_of(pack, name)) and parsed[1] < generation
    ]
    for name in old:
        search.delete_index(name)
    return old


def compiled_path(output_dir: Path, pack: str) -> Path:
    return output_dir / pack / "compiled.json"


def load_compiled(output_dir: Path, pack: str) -> CompiledPack:
    path = compiled_path(output_dir, pack)
    if not path.is_file():
        raise CompileError(f"{path} does not exist; compile the pack first")
    return CompiledPack.model_validate_json(path.read_text(encoding="utf-8"))


def compile_pack(
    pack_dir: Path,
    *,
    warehouse: Warehouse,
    top_k: int,
    search: OpenSearch | None = None,
    embeddings: EmbeddingClient | None = None,
    output_dir: Path | None = None,
    schema_dir: Path | None = None,
    skip_index: bool = False,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> CompileSummary:
    """Compile ``pack_dir``; with ``skip_index`` stop after the metric test-run."""
    pack = approved_pack(load_pack(pack_dir, schema_dir=schema_dir, catalog=WarehouseCatalog(warehouse)))
    summary = CompileSummary(
        pack=pack.name, metrics_tested=test_metrics(pack, warehouse), coverage=read_coverage(pack, warehouse)
    )
    if skip_index:
        return summary
    if search is None or embeddings is None or output_dir is None:
        raise CompileError("indexing needs a search client, an embedding client and an output directory")

    documents = build_documents(pack, read_column_values(pack, warehouse, top_k))
    generation, counts = build_generation(search, embeddings, pack.name, documents)
    compiled = CompiledPack(
        pack=pack, generation=generation, embedding_dimensions=embeddings.dimensions,
        coverage=summary.coverage, compiled_at=clock().isoformat(),
    )
    target = compiled_path(output_dir, pack.name)
    staged = target.with_suffix(".json.tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        staged.write_text(compiled.model_dump_json(indent=2), encoding="utf-8")
        swap_aliases(search, pack.name, generation)
    except Exception as error:
        staged.unlink(missing_ok=True)
        _delete_quietly(search, [physical_name(pack.name, index, generation) for index in INDEX_NAMES])
        raise CompileError(f"publishing index generation {generation} failed: {_first_line(error)}") from error
    os.replace(staged, target)
    delete_older_generations(search, pack.name, generation)
    summary.generation = generation
    summary.documents = counts
    return summary
