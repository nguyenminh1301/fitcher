"""Compile a Domain Pack into its search indices and ``compiled.json``.

Run with ``docker compose run --rm jobs python -m jobs.compile_pack --pack <name>``.
Indexing embeds every glossary term, metric, dataset, column and example
through the ``embed`` alias, which is a billable request sent with
``trusted_pack`` screening metadata; document chunks and column values are
screened first with the classifier in ``GUARD_MODEL_DIR`` and the report lists
what screening kept out or flagged; ``--skip-index``
stops after validation, the metric test-run and the access policies and calls
neither LiteLLM nor Qdrant.

The pack's policies are applied to ClickHouse as the admin user after the
metric test-run: roles, column grants, row policies, aggregate-only views and
one login user per role, whose passwords derive from
``CLICKHOUSE_AGENT_PASSWORD``.

``--check-search "<query>"`` searches the live aliases of an already compiled
pack instead of compiling, printing the best hits of each index.
"""

import argparse
import os
from pathlib import Path
import sys

from clickhouse_connect.driver.exceptions import Error as ClickHouseError

from app.config import SettingsError, load_settings
from app.llm.embeddings import EmbeddingError, LiteLLMEmbeddings
from app.packs.compiler import CompileError, CompileSummary, compile_pack, load_compiled
from app.observability.tracing import trusted_pack_calls
from app.packs.loader import PackValidationError
from app.packs.search_indices import search_pack
from app.screening.screen import Screener
from app.search.client import QdrantSearch, SearchError
from jobs.lib.clickhouse import admin_client

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PACKS_DIR = ROOT / "packs"
CHECK_SEARCH_SIZE = 3


class ClickHouseWarehouse:
    """Adapts a clickhouse-connect client to the compiler's Warehouse protocol."""

    def __init__(self, client):
        self._client = client

    def query(self, sql: str, settings: dict | None = None):
        return self._client.query(sql, settings=settings).result_rows

    def command(self, sql: str) -> None:
        self._client.command(sql)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pack", required=True, help="pack directory name under --packs-dir")
    parser.add_argument("--packs-dir", type=Path, default=DEFAULT_PACKS_DIR)
    parser.add_argument("--skip-index", action="store_true", help="validate and test-run metrics only")
    parser.add_argument("--check-search", metavar="QUERY", help="search the compiled pack instead of compiling")
    parser.add_argument("--role", action="append", help="role to search as; default: every role of the pack")
    return parser.parse_args(argv)


def print_summary(summary: CompileSummary) -> None:
    print(f"Pack {summary.pack}: {len(summary.metrics_tested)} metrics tested ({', '.join(summary.metrics_tested)})")
    roles = summary.roles_applied
    print(f"  access: {len(roles)} role{'' if len(roles) == 1 else 's'} reconciled ({', '.join(roles)})")
    for dataset, coverage in summary.coverage.items():
        print(f"  {dataset}: {coverage.rows} rows, {coverage.min_date} to {coverage.max_date}")
    if summary.generation is None:
        print("  indexing skipped")
        return
    print(f"  generation v{summary.generation} is live:")
    for index, count in summary.documents.items():
        print(f"    {index}: {count} documents")
    print(f"  screening: {len(summary.blocked_chunks)} document chunks not indexed, "
          f"{len(summary.flagged_values)} column values flagged and still indexed")
    for item in summary.blocked_chunks:
        print(f"    not indexed: {item}")
    for item in summary.flagged_values:
        print(f"    flagged: {item}")
    for warning in summary.warnings:
        print(f"  warning: {warning}")


def check_search(args: argparse.Namespace, settings, search: QdrantSearch, embeddings) -> int:
    compiled = load_compiled(Path(settings.compiled_pack_dir), args.pack)
    roles = args.role or [role.id for role in compiled.pack.policies.roles]
    results = search_pack(search, embeddings, args.pack, args.check_search, roles, CHECK_SEARCH_SIZE)
    print(f"Search {args.check_search!r} in {args.pack} as {', '.join(roles)}:")
    for index, hits in results.items():
        listed = ", ".join(f"{_hit_label(hit)} ({hit['score']:.3f})" for hit in hits) or "no hits"
        print(f"  {index}: {listed}")
    return 0


def _hit_label(hit: dict) -> str:
    source = hit["source"]
    if source.get("type") == "column_value":
        return f"{source['dataset']}.{source['column']}={source['title']!r}"
    return hit["id"]


def main(argv: list[str] | None = None) -> int:
    # Every gateway request of a compile embeds reviewed pack content or screened chunks (DECISIONS §9).
    with trusted_pack_calls():
        return _main(argv)


def _main(argv: list[str] | None) -> int:
    args = parse_args(argv)
    try:
        settings = load_settings()
        search = QdrantSearch(settings.qdrant_url)
        if args.check_search is not None:
            embeddings = LiteLLMEmbeddings(
                settings.litellm_base_url, settings.litellm_master_key, settings.embedding_dimensions
            )
            return check_search(args, settings, search, embeddings)

        embeddings = None
        if not args.skip_index:
            embeddings = LiteLLMEmbeddings(
                settings.litellm_base_url, settings.litellm_master_key, settings.embedding_dimensions
            )
        warehouse = ClickHouseWarehouse(admin_client())
        summary = compile_pack(
            args.packs_dir / args.pack,
            warehouse=warehouse,
            access=warehouse,
            agent_secret=os.environ.get("CLICKHOUSE_AGENT_PASSWORD", ""),
            top_k=settings.column_values_top_k,
            search=search,
            embeddings=embeddings,
            output_dir=Path(settings.compiled_pack_dir),
            skip_index=args.skip_index,
            screener=Screener.from_settings(settings),
        )
    except (PackValidationError, CompileError, SettingsError, SearchError, EmbeddingError, ClickHouseError) as error:
        print(error, file=sys.stderr)
        return 1
    print_summary(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
