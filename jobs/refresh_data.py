"""Refresh one source: load or attach its tables, then build its dbt models and tests.

Run with ``docker compose run --rm jobs python -m jobs.refresh_data --source <name>``.
A Hugging Face source is downloaded by ``jobs.load_data``; any other source is
copied into ``raw`` or attached live by ``jobs.sync_sources``, and dbt receives
the relations of its tables in that mode as variables (DECISIONS §4 Data sources).

ClickHouse cannot swap several tables atomically, so consistency comes from
``data_meta.refresh_log``. Each refresh takes the next generation for its
source and records ``started``, then ``completed`` only after the load and every
dbt model and test succeed, or ``failed`` otherwise. A reader trusts a source's
data only when the latest row before and after its operation is the same
``completed`` generation.

Concurrent refreshes of one source are rejected by a lock table: ``CREATE
TABLE`` without ``IF NOT EXISTS`` succeeds for exactly one caller. A crashed
refresh leaves the lock behind; the error names the ``DROP TABLE`` to run once
no refresh is active.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from jobs.lib.clickhouse import admin_client, sources_client
from jobs.lib.source_engines import relations
from jobs.lib.source_manifest import HUGGINGFACE, ManifestError, SourceManifest, load_manifest
from jobs.load_data import DEFAULT_DATA_DIR, LoadError, load_source, print_summary
from jobs.sync_sources import sync_source, with_mode

META_DATABASE = "data_meta"
LOG_TABLE = "refresh_log"
REFRESH_LOG = f"`{META_DATABASE}`.`{LOG_TABLE}`"
LOG_COLUMNS = ["source", "generation", "state", "message"]
MESSAGE_LIMIT = 1000
CREATE_LOG = (
    f"CREATE TABLE IF NOT EXISTS {REFRESH_LOG} ("
    "source String, "
    "generation UInt64, "
    "state Enum8('started' = 1, 'completed' = 2, 'failed' = 3), "
    "ts DateTime64(3, 'UTC') DEFAULT now64(3), "
    "message String DEFAULT ''"
    ") ENGINE = MergeTree ORDER BY (source, generation, ts)"
)


class RefreshError(RuntimeError):
    """A refresh did not complete; its generation is recorded as failed when one was taken."""


def lock_table(source: str) -> str:
    return f"`{META_DATABASE}`.`refresh_lock_{source}`"


def dbt_vars(manifest: SourceManifest) -> dict | None:
    """Variables that point the source's staging models at its tables; None for a Hugging Face source."""
    if manifest.kind == HUGGINGFACE:
        return None
    return {"source_name": manifest.name, "source_mode": manifest.mode, "source_tables": relations(manifest)}


def run_dbt_build(manifest: SourceManifest) -> int:
    # The leading + selects upstream staging models, so changed raw data reaches the marts.
    command = ["dbt", "build", "--project-dir", "dbt", "--profiles-dir", "dbt", "--select", f"+tag:{manifest.dbt_tag}"]
    variables = dbt_vars(manifest)
    if variables is not None:
        command += ["--vars", json.dumps(variables)]
    return subprocess.run(command, check=False).returncode


def sync_as_source_loader(manifest: SourceManifest, client, data_dir: Path, revision: str | None = None):
    """Sync with the source_loader connection; ``client`` stays the admin one that writes the refresh log."""
    return sync_source(manifest, sources_client())


def refresh(
    manifest: SourceManifest,
    client,
    data_dir: Path,
    revision: str | None = None,
    load=load_source,
    build=run_dbt_build,
) -> int:
    client.command(CREATE_LOG)
    _acquire_lock(client, manifest.name)
    try:
        generation = _next_generation(client, manifest.name)
        _log(client, manifest.name, generation, "started")
        try:
            try:
                print_summary(load(manifest, client, data_dir, revision=revision))
            except LoadError as error:
                print_summary(error.results)
                raise
            code = build(manifest)
            if code != 0:
                raise RefreshError(f"dbt build for tag {manifest.dbt_tag!r} exited with code {code}")
        except Exception as error:
            _log(client, manifest.name, generation, "failed", str(error)[:MESSAGE_LIMIT])
            raise RefreshError(f"refresh of {manifest.name} generation {generation} failed: {error}") from error
        _log(client, manifest.name, generation, "completed")
        return generation
    finally:
        client.command(f"DROP TABLE IF EXISTS {lock_table(manifest.name)}")


def _acquire_lock(client, source: str) -> None:
    try:
        client.command(f"CREATE TABLE {lock_table(source)} (acquired DateTime DEFAULT now()) ENGINE = Memory")
    except Exception as error:
        if "TABLE_ALREADY_EXISTS" not in str(error):
            raise RefreshError(f"could not take the refresh lock for {source}: {error}") from error
        raise RefreshError(
            f"another refresh of {source} holds the lock. If no refresh is running, "
            f"remove the stale lock with: DROP TABLE {META_DATABASE}.refresh_lock_{source}"
        ) from error


def _next_generation(client, source: str) -> int:
    latest = client.command(
        f"SELECT max(generation) FROM {REFRESH_LOG} WHERE source = {{source:String}}",
        parameters={"source": source},
    )
    return int(latest) + 1


def _log(client, source: str, generation: int, state: str, message: str = "") -> None:
    client.insert(
        LOG_TABLE,
        [[source, generation, state, message]],
        database=META_DATABASE,
        column_names=LOG_COLUMNS,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load one source and build its dbt models and tests.")
    parser.add_argument("--source", required=True, help="manifest name under jobs/sources")
    parser.add_argument("--revision", help="override the manifest's pinned revision")
    parser.add_argument("--mode", choices=["copy", "live"], help="override the manifest's mode")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    args = parser.parse_args(argv)

    try:
        manifest = with_mode(load_manifest(args.source), args.mode)
        load = load_source if manifest.kind == HUGGINGFACE else sync_as_source_loader
        generation = refresh(manifest, admin_client(), args.data_dir, args.revision, load=load, build=run_dbt_build)
    except (ManifestError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1

    print(f"Refresh of {manifest.name}: generation {generation} completed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
