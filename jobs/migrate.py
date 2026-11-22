"""Apply the pending numbered schema changes to the app state and to ClickHouse.

Run with ``docker compose run --rm jobs python -m jobs.migrate``.

Each store records what it applied: ``schema_changes`` in
``<FITCHER_DATA_DIR>/app.db`` and ``data_meta.schema_changes`` in ClickHouse.
A second run applies nothing. The ClickHouse files in
``infra/clickhouse/changes`` are also what the ClickHouse entrypoint runs on a
fresh volume; every statement only creates what is missing, adds a missing
column or sets a column to the type it may already have, so applying them to
a volume created before this runner existed changes nothing and records them
as applied. ClickHouse has no transactional DDL, so a ClickHouse change must
stay idempotent. A store that records a change this version does not know was
written by a newer one and is refused.
"""

import argparse
from pathlib import Path
import sys

from app.state.db import StateDb, data_dir
from app.state.migrate import MigrationError, apply_pending, check_not_newer, discover
from jobs.lib.clickhouse import admin_client

CLICKHOUSE_CHANGES_DIR = Path(__file__).resolve().parents[1] / "infra" / "clickhouse" / "changes"

REGISTRY_STATEMENTS = (
    "CREATE DATABASE IF NOT EXISTS data_meta",
    "CREATE TABLE IF NOT EXISTS data_meta.schema_changes\n"
    "(\n    number UInt32,\n    name String,\n    applied_at DateTime64(3, 'UTC') DEFAULT now64(3)\n)\n"
    "ENGINE = MergeTree\nORDER BY number",
)


def apply_clickhouse(client, directory: Path = CLICKHOUSE_CHANGES_DIR) -> list[int]:
    """Apply the changes ClickHouse has not recorded; return their numbers."""
    changes = discover(directory)
    for statement in REGISTRY_STATEMENTS:
        client.command(statement)
    recorded = {row[0] for row in client.query("SELECT number FROM data_meta.schema_changes").result_rows}
    check_not_newer(recorded, changes, "ClickHouse")
    applied: list[int] = []
    for change in changes:
        if change.number in recorded:
            continue
        try:
            for statement in change.statements():
                client.command(statement)
        except Exception as error:
            raise MigrationError(f"change {change.label} failed: {error}") from error
        client.insert("data_meta.schema_changes", [[change.number, change.name]], column_names=["number", "name"])
        applied.append(change.number)
    return applied


def report(store: str, applied: list[int]) -> None:
    if applied:
        print(f"{store}: applied {', '.join(f'{n:04d}' for n in applied)}.")
    else:
        print(f"{store}: up to date.")


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args(argv)
    try:
        report("ClickHouse", apply_clickhouse(admin_client()))
        db = StateDb(data_dir() / "app.db")
        try:
            report("App state", apply_pending(db))
        finally:
            db.close()
    except (RuntimeError, MigrationError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
