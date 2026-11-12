"""Numbered schema changes (``NNNN_name.sql``) for the app state.

``apply_pending`` applies the changes the store has not recorded, in order,
each inside one transaction together with its ``schema_changes`` row. A store
that records a number the code does not know was written by a newer version
and is refused. ``jobs.migrate`` uses the same file naming for ClickHouse.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import re

from app.state.db import StateDb

CHANGES_DIR = Path(__file__).parent / "changes"
NAME = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")


class MigrationError(RuntimeError):
    """A change cannot be applied, or the store is not compatible with this version."""


@dataclass(frozen=True)
class Change:
    number: int
    name: str
    path: Path

    @property
    def label(self) -> str:
        return f"{self.number:04d}_{self.name}"

    def statements(self) -> list[str]:
        return split_statements(self.path.read_text(encoding="utf-8"))


def split_statements(sql: str) -> list[str]:
    """Statements of ``sql`` without ``--`` comment lines or blank parts.

    A statement must not contain a semicolon inside a string literal.
    """
    code = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
    return [statement.strip() for statement in code.split(";") if statement.strip()]


def discover(directory: Path) -> list[Change]:
    """The changes in ``directory`` ordered by number; numbers start at 1 and have no gap."""
    changes: list[Change] = []
    for path in sorted(directory.glob("*.sql")):
        match = NAME.match(path.name)
        if match is None:
            raise MigrationError(f"{path.name} is not named NNNN_name.sql")
        changes.append(Change(int(match.group(1)), match.group(2), path))
    seen: set[int] = set()
    for change in changes:
        if change.number in seen:
            raise MigrationError(f"change number {change.number:04d} appears twice")
        seen.add(change.number)
    for expected, change in enumerate(changes, start=1):
        if change.number != expected:
            raise MigrationError(f"gap in change numbers: expected {expected:04d}, found {change.number:04d}")
    return changes


def check_not_newer(recorded: set[int], known: list[Change], store: str) -> None:
    newest = max(recorded, default=0)
    if newest > len(known):
        raise MigrationError(
            f"{store} was written by a newer version (it records change {newest:04d}, this version knows {len(known):04d}); "
            "run a newer image"
        )


def apply_pending(db: StateDb, directory: Path = CHANGES_DIR) -> list[int]:
    """Apply the changes of ``directory`` the store has not recorded; return their numbers."""
    changes = discover(directory)
    with db.write() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_changes "
            "(number INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
    recorded = {row[0] for row in db.connection().execute("SELECT number FROM schema_changes")}
    check_not_newer(recorded, changes, "the app state")
    applied: list[int] = []
    for change in changes:
        if change.number in recorded:
            continue
        try:
            with db.write() as conn:
                for statement in change.statements():
                    conn.execute(statement)
                conn.execute(
                    "INSERT INTO schema_changes (number, name, applied_at) VALUES (?, ?, ?)",
                    (change.number, change.name, datetime.now(UTC).isoformat()),
                )
        except Exception as error:
            raise MigrationError(f"change {change.label} failed and was rolled back: {error}") from error
        applied.append(change.number)
    return applied
