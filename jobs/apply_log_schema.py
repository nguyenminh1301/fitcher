"""Create the ``agent_logs`` tables and ``data_meta.model_tiers`` on an existing ClickHouse volume.

Run with ``docker compose run --rm jobs python -m jobs.apply_log_schema``.

The ClickHouse entrypoint runs ``infra/clickhouse/initdb`` only on a fresh
volume; this job applies the same files to a volume created before they existed.
Every statement is ``CREATE ... IF NOT EXISTS`` or ``ALTER TABLE ... ADD
COLUMN IF NOT EXISTS``, so running it again changes nothing; on a volume that
predates a column, it adds the column and leaves existing rows in place.
"""

import argparse
from pathlib import Path
import sys

from jobs.lib.clickhouse import admin_client

INITDB = Path(__file__).resolve().parents[1] / "infra" / "clickhouse" / "initdb"
SCHEMA_FILE = INITDB / "010-agent-logs.sql"
# Applied in order; 001-databases.sql already created data_meta on every volume.
SCHEMA_FILES = (SCHEMA_FILE, INITDB / "020-model-tiers.sql")


def split_statements(sql: str) -> list[str]:
    """Statements of ``sql`` without ``--`` comment lines or blank parts."""
    code = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
    return [statement.strip() for statement in code.split(";") if statement.strip()]


def apply_schema(client, sql: str) -> int:
    statements = split_statements(sql)
    for statement in statements:
        client.command(statement)
    return len(statements)


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args(argv)
    try:
        client = admin_client()
        for path in SCHEMA_FILES:
            count = apply_schema(client, path.read_text(encoding="utf-8"))
            print(f"Applied {count} statements from {path.name}.")
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
