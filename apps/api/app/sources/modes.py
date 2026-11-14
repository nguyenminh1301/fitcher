"""Live or copy for each table of a source (DECISIONS §4 Data sources, §14).

Live is the default for a small table: nothing is stored twice and answers are always fresh. A table at or above
1 million rows or 1 GB, whichever the source reports (either limit decides), is proposed as a copy, because
ClickHouse pushes only simple filters to a source and runs joins, aggregation and sorting itself after reading
the rows. A view of the source runs its own query there on every read, so it is proposed as a copy as well.
The user can override either proposal.
"""

from dataclasses import dataclass

from app.sources.inspect import TableInfo

LIVE_ROW_LIMIT = 1_000_000
GIB = 1024**3


@dataclass(frozen=True)
class Proposal:
    mode: str
    # small, unknown_size, rows, size, view or copy_only: the interface words the reason from this code.
    reason: str


def propose(table: TableInfo, copy_only: bool = False) -> Proposal:
    """The mode of a table; a source that cannot be read live (SQL Server) always gets a copy."""
    if copy_only:
        return Proposal("copy", "copy_only")
    if table.kind == "view":
        return Proposal("copy", "view")
    if table.rows is not None and table.rows >= LIVE_ROW_LIMIT:
        return Proposal("copy", "rows")
    if table.size_bytes is not None and table.size_bytes >= GIB:
        return Proposal("copy", "size")
    if table.rows is None and table.size_bytes is None:
        return Proposal("live", "unknown_size")
    return Proposal("live", "small")


def joined_live_tables(tables: list[TableInfo], modes: dict[str, str]) -> set[str]:
    """The tables read live that a foreign key ties to another table read live.

    A mart that joins them makes ClickHouse read both over the network and join the rows itself, which is slow
    for anything but small tables; the Sources page flags them and suggests a copy.
    """
    live = {name for name, mode in modes.items() if mode == "live"}
    flagged: set[str] = set()
    for table in tables:
        if table.name not in live:
            continue
        for key in table.foreign_keys:
            if key.ref_table in live and key.ref_table != table.name:
                flagged |= {table.name, key.ref_table}
    return flagged


# Source column types an incremental copy can follow: they only grow (numbers) or move forward (dates).
CURSOR_TYPES = frozenset({
    "smallint", "integer", "bigint", "numeric", "real", "double precision", "date", "timestamp", "datetime2", "smalldatetime",
    "timestamp without time zone", "timestamp with time zone", "tinyint", "int", "mediumint", "decimal", "datetime",
    "year",
})


def cursor_candidates(columns) -> list[str]:
    """The columns of a table that can serve as an incremental copy's cursor, in column order."""
    return [column.name for column in columns if column.type.lower() in CURSOR_TYPES]
