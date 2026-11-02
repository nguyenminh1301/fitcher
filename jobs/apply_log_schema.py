"""Create the ``agent_logs`` database and tables on an existing ClickHouse volume.

Run with ``docker compose run --rm jobs python -m jobs.apply_log_schema``.

The ClickHouse entrypoint runs ``infra/clickhouse/initdb`` only on a fresh
volume; this job applies the same file to a volume created before it existed.
Every statement is ``CREATE ... IF NOT EXISTS``, so running it again changes
nothing and never alters a table that already exists.
"""

import argparse
from pathlib import Path
import sys

from jobs.lib.clickhouse import admin_client

SCHEMA_FILE = Path(__file__).resolve().parents[1] / "infra" / "clickhouse" / "initdb" / "010-agent-logs.sql"


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
        count = apply_schema(admin_client(), SCHEMA_FILE.read_text(encoding="utf-8"))
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 1
    print(f"Applied {count} statements from {SCHEMA_FILE.name}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
