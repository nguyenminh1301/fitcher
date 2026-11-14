"""Compile a Domain Pack into the artifacts the runtime reads.

The order is fixed: load and validate the pack against its schemas, its own
references and the warehouse catalog; keep approved items only; test-run every
metric; reconcile the ClickHouse roles, grants, row policies, views and users
of the pack's policies; read each dataset's date coverage and the top values of
indexable columns; screen document chunks and column values (DECISIONS §9);
write a new generation of the six Qdrant collections; move all six
aliases in one request; write ``compiled.json``; and only then delete older
generations. A failure before the alias move deletes the partial generation
and leaves the live aliases untouched.

``kb_docs`` is rebuilt from the document registry: the chunks of every
``indexed`` document are copied with their vectors from the live generation
when ``compiled.json`` names the same embedding alias and dimensions, and
otherwise each stored file is parsed, chunked, screened and embedded again.

Screening drops a ``kb_docs`` chunk whose verdict is ``block`` or, without
the classifier, ``unavailable``, and lists it in the summary; a column value
that is flagged or blocked is listed and still indexed, because it is real
data the filters need. Reviewed pack content is trusted and not screened.
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

from app.data.forbidden_functions import forbidden_function
from app.onboarding.chunker import chunk_sections
from app.onboarding.docs_parser import DocumentRejected, parse_document
from app.onboarding.documents import KB_DOCS, DocumentRegistry, chunk_payloads
from app.llm.embeddings import EmbeddingClient
from app.packs.loader import check_references, load_pack
from app.packs.models import Pack
from app.packs.policy_compiler import AccessControl, apply_policies, memory_cap
from app.packs.search_indices import INDEX_NAMES, ColumnValue, alias_name, build_documents, generation_of, physical_name, points
from app.screening.screen import Screener
from app.search.client import QdrantSearch

MARTS_DATABASE = "marts"
# readonly=2 allows only reads while still letting the query carry its own settings.
METRIC_TEST_SETTINGS = {"max_execution_time": 30, "readonly": 2}
# Catalog, coverage and top-value scans read whole tables, so they get more time but a memory cap.
SCAN_SETTINGS = {"max_execution_time": 300, "max_memory_usage": 2_000_000_000, "readonly": 2}
ERROR_LIMIT = 500
# Characters of a flagged column value shown in the compile report.
SHOWN_VALUE = 80
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
                f"SELECT table, name FROM system.columns WHERE database = '{MARTS_DATABASE}'", settings=SCAN_SETTINGS
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
    # The embed tier's alias the vectors came from; a recompile with another alias re-embeds documents.
    embedding_alias: str = ""


@dataclass
class CompileSummary:
    pack: str
    metrics_tested: list[str]
    coverage: dict[str, DateCoverage]
    roles_applied: list[str] = field(default_factory=list)
    generation: int | None = None
    documents: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    # Document chunks screening kept out of kb_docs, and column values it flagged or blocked (still indexed).
    blocked_chunks: list[str] = field(default_factory=list)
    flagged_values: list[str] = field(default_factory=list)


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
    """Raise ValueError unless ``sql_expr`` parses as exactly one scalar expression the SQL guard would accept."""
    # Parsing into a condition accepts expressions only: statements, a second
    # statement after ";" and trailing clauses such as FROM are parse errors.
    try:
        node = sqlglot.parse_one(sql_expr, read="clickhouse", into=exp.Condition)
    except sqlglot.errors.ParseError as error:
        raise ValueError(f"does not parse as one expression: {_first_line(error)}") from None
    if node.find(exp.Query, exp.Subquery):
        raise ValueError("must not contain a subquery")
    if name := forbidden_function(node):
        raise ValueError(f"function {name}() is not allowed")


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
            f"SELECT count(), min({column}), max({column}) FROM {table_ref(dataset.id)}", settings=SCAN_SETTINGS
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
                f"WHERE value != '' GROUP BY value ORDER BY n DESC, value LIMIT {int(top_k)}",
                settings=SCAN_SETTINGS,
            )
            values.extend(ColumnValue(dataset.id, column.name, value, count) for value, count in rows)
    return values


def _screen_note(verdict) -> str:
    return f"{verdict.verdict}" + (f": {', '.join(verdict.rule_hits)}" if verdict.rule_hits else "") + (
        f", score {verdict.score:.3f}" if verdict.score is not None else ""
    )


def screen_documents(documents: dict[str, list[dict]], screener: Screener, summary: CompileSummary) -> None:
    """Drop blocked kb_docs chunks and report flagged column values, recording both in ``summary``."""
    chunks = documents["kb_docs"]
    kept: list[dict] = []
    for chunk, verdict in zip(chunks, screener.screen_many([chunk["text"] for chunk in chunks], "document"), strict=True):
        if verdict.verdict in ("block", "unavailable"):
            summary.blocked_chunks.append(f"{chunk['id']} ({_screen_note(verdict)})")
        else:
            kept.append(chunk)
    documents["kb_docs"] = kept
    values = documents["column_values"]
    texts = [value["payload"]["value"] for value in values]
    for value, verdict in zip(values, screener.screen_many(texts, "column_value"), strict=True):
        if verdict.verdict in ("flag", "block") or verdict.rule_hits:
            shown = value["payload"]["value"][:SHOWN_VALUE]
            summary.flagged_values.append(f"{value['dataset']}.{value['column']}={shown!r} ({_screen_note(verdict)})")
    if screener.state == "disabled":
        summary.warnings.append(
            "the screening classifier is off: documents and column values were checked by the rules only"
        )
    elif screener.state == "unavailable":
        summary.warnings.append(
            "the screening classifier is unavailable: column values were checked by the rules only "
            "and no document chunk was indexed"
        )


def _delete_quietly(search: QdrantSearch, names: Sequence[str]) -> None:
    for name in names:
        try:
            search.delete_collection(name)
        except Exception:  # noqa: BLE001, S110 - cleanup must not hide the original failure
            pass


def next_generation(search: QdrantSearch, pack: str) -> int:
    generations = [parsed[1] for name in search.list_collections() if (parsed := generation_of(pack, name))]
    return max(generations, default=0) + 1


def _live_compiled(output_dir: Path, pack: str) -> CompiledPack | None:
    try:
        return load_compiled(output_dir, pack)
    except (CompileError, ValueError):
        return None


def registry_chunks(
    search: QdrantSearch, pack: str, registry: DocumentRegistry, documents_dir: Path, live: CompiledPack | None,
    embedding_alias: str, dimensions: int, summary: "CompileSummary",
) -> tuple[list[dict], list[dict]]:
    """``(points copied from the live kb_docs, chunk documents to screen and embed)`` of the indexed documents."""
    indexed = {record.id: record for record in registry.list(pack) if record.status == "indexed"}
    if not indexed:
        return [], []
    alias = alias_name(pack, KB_DOCS)
    same_model = (
        live is not None and live.embedding_alias == embedding_alias and live.embedding_dimensions == dimensions
        and alias in search.alias_targets()
    )
    if same_model:
        live_points = search.scroll(alias, with_vectors=True)
        return [
            {"id": point["id"], "vector": point["vector"], "payload": point["payload"]}
            for point in live_points if point["payload"].get("document_id") in indexed
        ], []
    fresh: list[dict] = []
    for record in indexed.values():
        path = documents_dir / pack / record.id
        if not path.is_file():
            summary.warnings.append(f"document {record.id} ({record.file_name}) has no stored file and was not indexed")
            continue
        try:
            chunks = chunk_sections(parse_document(path.read_bytes(), record.media_type), record.media_type)
        except DocumentRejected as error:
            summary.warnings.append(f"document {record.id} ({record.file_name}) cannot be parsed again: {error}")
            continue
        fresh.extend(chunk_payloads(record, chunks))
    return [], fresh


def build_generation(
    search: QdrantSearch, embeddings: EmbeddingClient, pack: str, documents: dict[str, list[dict]],
    carried: dict[str, list[dict]] | None = None,
) -> tuple[int, dict[str, int]]:
    """Create and fill generation N+1 of every collection; delete it again on any failure.

    ``carried`` holds ready points per index, copied with their vectors and not embedded again.
    """
    carried = carried or {}
    generation = next_generation(search, pack)
    created: list[str] = []
    counts: dict[str, int] = {}
    try:
        for index in INDEX_NAMES:
            name = physical_name(pack, index, generation)
            search.create_collection(name, embeddings.dimensions)
            created.append(name)
            docs = documents[index]
            vectors = embeddings.embed([document["embedding_text"] for document in docs]) if docs else []
            search.upsert(name, [*points(name, docs, vectors), *carried.get(index, [])])
            counts[index] = search.count(name)
            expected = len(docs) + len(carried.get(index, []))
            if counts[index] != expected:
                raise CompileError(f"{name} holds {counts[index]} points, expected {expected}")
    except Exception as error:
        _delete_quietly(search, created)
        raise CompileError(f"building index generation {generation} failed: {_first_line(error)}") from error
    return generation, counts


def swap_aliases(search: QdrantSearch, pack: str, generation: int) -> None:
    """Point all six aliases at ``generation`` in one atomic request, so a reader never sees a mixed generation."""
    current = search.alias_targets()
    actions: list[dict] = []
    for index in INDEX_NAMES:
        alias = alias_name(pack, index)
        if alias in current:
            actions.append({"delete_alias": {"alias_name": alias}})
        actions.append({"create_alias": {"collection_name": physical_name(pack, index, generation), "alias_name": alias}})
    search.update_aliases(actions)


def delete_older_generations(search: QdrantSearch, pack: str, generation: int) -> list[str]:
    old = [name for name in search.list_collections() if (parsed := generation_of(pack, name)) and parsed[1] < generation]
    for name in old:
        search.delete_collection(name)
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
    search: QdrantSearch | None = None,
    embeddings: EmbeddingClient | None = None,
    output_dir: Path | None = None,
    schema_dir: Path | None = None,
    skip_index: bool = False,
    access: AccessControl | None = None,
    agent_secret: str = "",
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    screener: Screener | None = None,
    registry: DocumentRegistry | None = None,
    documents_dir: Path | None = None,
    embedding_alias: str = "",
) -> CompileSummary:
    """Compile ``pack_dir``; with ``skip_index`` stop after the metric test-run and the access policies.

    With ``access``, the admin connection, the pack's policies are applied to
    ClickHouse; its users' passwords derive from ``agent_secret``. Without
    ``screener`` indexing screens with no classifier, so no document chunk is indexed.
    With ``registry`` and ``documents_dir``, ``kb_docs`` holds the pack's indexed documents.
    """
    pack = approved_pack(load_pack(pack_dir, schema_dir=schema_dir, catalog=WarehouseCatalog(warehouse)))
    metrics_tested = test_metrics(pack, warehouse)
    roles_applied: list[str] = []
    if access is not None:
        if not agent_secret:
            raise CompileError("CLICKHOUSE_AGENT_PASSWORD must be set to apply the access policies")
        apply_policies(pack, access, agent_secret, memory_cap())
        roles_applied = [role.id for role in pack.policies.roles]
    summary = CompileSummary(
        pack=pack.name, metrics_tested=metrics_tested, coverage=read_coverage(pack, warehouse),
        roles_applied=roles_applied,
    )
    if skip_index:
        return summary
    if search is None or embeddings is None or output_dir is None:
        raise CompileError("indexing needs a search client, an embedding client and an output directory")

    documents = build_documents(pack, read_column_values(pack, warehouse, top_k))
    carried: list[dict] = []
    if registry is not None and documents_dir is not None:
        carried, fresh = registry_chunks(
            search, pack.name, registry, documents_dir, _live_compiled(output_dir, pack.name), embedding_alias,
            embeddings.dimensions, summary,
        )
        documents[KB_DOCS].extend(fresh)
    screen_documents(documents, screener or Screener(None), summary)
    generation, counts = build_generation(search, embeddings, pack.name, documents, {KB_DOCS: carried})
    compiled = CompiledPack(
        pack=pack, generation=generation, embedding_dimensions=embeddings.dimensions,
        coverage=summary.coverage, compiled_at=clock().isoformat(), embedding_alias=embedding_alias,
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
    try:
        delete_older_generations(search, pack.name, generation)
    except Exception as error:  # noqa: BLE001 - the new generation is already live
        summary.warnings.append(f"older index generations were not deleted: {_first_line(error)}")
    summary.generation = generation
    summary.documents = counts
    return summary
