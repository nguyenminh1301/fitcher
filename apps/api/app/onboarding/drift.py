"""Schema drift of an instant pack's source (DECISIONS §11 step 0; detected and reported, never re-drafted).

The instant job saves the columns of the chosen tables, as the source's catalog listed them, in
``<pack dir>/instant_source.json``. Comparing that snapshot with the catalog now shows, per table, the columns
added, removed and retyped since the pack was built, and a table the source no longer lists. Rebuilding the pack
is the user's action.
"""

from collections.abc import Sequence
import json
from pathlib import Path

SNAPSHOT = "instant_source.json"


def write_snapshot(pack_dir: Path, source_id: str, tables: Sequence) -> None:
    data = {"source": source_id,
            "tables": {table.name: [[column.name, column.type] for column in table.columns] for table in tables}}
    (Path(pack_dir) / SNAPSHOT).write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")


def read_snapshot(pack_dir: Path) -> dict | None:
    path = Path(pack_dir) / SNAPSHOT
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def schema_drift(snapshot: dict, current: Sequence) -> list[dict]:
    """The changed tables of ``snapshot`` against the catalog ``current`` (``StoredTable`` items)."""
    now = {table.name: {column.name: column.type for column in table.columns} for table in current}
    changes = []
    for table, columns in snapshot["tables"].items():
        before = dict((name, kind) for name, kind in columns)
        after = now.get(table, {})
        change = {
            "table": table,
            "added": [name for name in after if name not in before],
            "removed": [name for name in before if name not in after],
            "retyped": [{"column": name, "before": kind, "after": after[name]}
                        for name, kind in before.items() if name in after and after[name] != kind],
            "missing": table not in now,
        }
        if change["added"] or change["removed"] or change["retyped"] or change["missing"]:
            changes.append(change)
    return changes
