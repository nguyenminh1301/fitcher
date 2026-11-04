"""Copy a source into ClickHouse ``raw``, or define its live database.

Run with ``docker compose run --rm jobs python -m jobs.sync_sources --source <name>``.
The job connects as ``source_loader``, the only ClickHouse user that may use
the source named collections, so it never reads a source credential itself
(DECISIONS §4 Data sources).

Copy mode reads each table through its table function into
``raw.<source>__<table>__loading`` and counts it. Only when every table with
an expected row count matches is each loading table exchanged into
``raw.<source>__<table>``; any failure drops the loading tables and leaves the
published copies untouched, so running the job again is always safe.

Live mode creates ``src_<source>`` with the manifest's database or table
engines and counts each table through them, which proves the source answers.
``--mode`` overrides the manifest's mode, for example to compare both modes.
dbt then builds the source's models; ``jobs.refresh_data`` runs both steps.
"""

import argparse
import dataclasses
import sys

from jobs.lib.clickhouse import sources_client
from jobs.lib.source_engines import live_statements, raw_table, relations, table_function
from jobs.lib.source_manifest import HUGGINGFACE, ManifestError, SourceManifest, load_manifest
from jobs.load_data import LoadError, TableResult, loading_table, print_summary, publish_raw_table


def with_mode(manifest: SourceManifest, mode: str | None) -> SourceManifest:
    return manifest if mode is None else dataclasses.replace(manifest, mode=mode)


def sync_source(manifest: SourceManifest, client, data_dir=None, revision=None) -> list[TableResult]:
    """Copy or attach ``manifest``; the unused arguments match ``jobs.load_data.load_source``."""
    if manifest.kind == HUGGINGFACE:
        raise ValueError(f"{manifest.name} is a {HUGGINGFACE} source; load it with jobs.load_data")
    if manifest.mode == "live":
        return _attach_live(manifest, client)
    return _copy(manifest, client)


def _copy(manifest: SourceManifest, client) -> list[TableResult]:
    _drop_loading(manifest, client)
    results: list[TableResult] = []
    try:
        for table in manifest.tables:
            loading = loading_table(raw_table(manifest, table))
            client.command(
                f"CREATE TABLE {loading} ENGINE = MergeTree ORDER BY tuple() "
                f"AS SELECT * FROM {table_function(manifest, table)}"
            )
            results.append(TableResult(table.name, table.expected_rows, int(client.command(f"SELECT count() FROM {loading}"))))
    except Exception as error:
        _drop_loading(manifest, client)
        failed = manifest.tables[len(results)].name
        raise LoadError(f"table {failed!r} failed to copy: {error}", results) from error

    mismatched = [result.name for result in results if not result.ok]
    if mismatched:
        _drop_loading(manifest, client)
        raise LoadError(f"row counts do not match the manifest for {mismatched}", results)
    for table in manifest.tables:
        publish_raw_table(client, raw_table(manifest, table))
    return results


def _attach_live(manifest: SourceManifest, client) -> list[TableResult]:
    for statement in live_statements(manifest):
        client.command(statement)
    results = [
        TableResult(table.name, table.expected_rows, int(client.command(f"SELECT count() FROM {relation}")))
        for table, relation in zip(manifest.tables, relations(manifest).values(), strict=True)
    ]
    mismatched = [result.name for result in results if not result.ok]
    if mismatched:
        raise LoadError(f"row counts do not match the manifest for {mismatched}", results)
    return results


def _drop_loading(manifest: SourceManifest, client) -> None:
    for table in manifest.tables:
        client.command(f"DROP TABLE IF EXISTS {loading_table(raw_table(manifest, table))}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Copy a source into raw or define its live src_ database.")
    parser.add_argument("--source", required=True, help="manifest name under jobs/sources")
    parser.add_argument("--mode", choices=["copy", "live"], help="override the manifest's mode")
    args = parser.parse_args(argv)

    try:
        manifest = with_mode(load_manifest(args.source), args.mode)
        results = sync_source(manifest, sources_client())
    except LoadError as error:
        print_summary(error.results)
        print(f"Sync failed, nothing was published: {error}", file=sys.stderr)
        return 1
    except (ManifestError, RuntimeError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1

    print_summary(results)
    if manifest.mode == "live":
        print(f"Defined {len(results)} live tables of {manifest.name} in src_{manifest.name}")
    else:
        print(f"Copied {len(results)} tables of {manifest.name} into raw")
    return 0


if __name__ == "__main__":
    sys.exit(main())
