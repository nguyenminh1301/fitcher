"""Sources, their tables and their syncs in the app state (DECISIONS §4, §15).

A source's credentials are not stored here: they live in the ClickHouse named collection named after the
source. The state keeps what the interface shows and the scheduler needs: the connection fields that are not
secret, the tables of the source's catalog with the user's choices (selection, mode, interval, cursor) and one
row per sync.

SQLite has no row locks, so one sync per source is enforced by the database itself: a partial unique index
allows a single ``running`` row per source, and the due check claims sources inside one immediate transaction.
A second api process therefore finds the source already syncing and skips it. A running row whose heartbeat
stopped belongs to a process that died and is marked ``failed`` with the reason ``interrupted``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import json
import sqlite3

from app.sources.attach import valid_name
from app.sources.inspect import CatalogColumn, ForeignKey, TableInfo
from app.sources.modes import propose
from app.state.db import StateDb

MODES = ("live", "copy")
MIN_INTERVAL_SECONDS = 60
DEFAULT_INTERVAL_SECONDS = 86_400
STALE_AFTER = timedelta(minutes=2)
STARTERS = ("manual", "schedule", "setup")


class SourceNotFound(LookupError):
    pass


class TableNotFound(LookupError):
    pass


class DuplicateSource(ValueError):
    pass


class SyncBusy(RuntimeError):
    """A sync of this source is already running."""


class _Unset:
    def __repr__(self) -> str:
        return "UNSET"


UNSET = _Unset()


@dataclass(frozen=True)
class NewSource:
    id: str
    kind: str
    host: str | None = None
    port: int | None = None
    database: str | None = None
    schema: str | None = None
    username: str | None = None
    tls_mode: str = "prefer"
    has_ca: bool = False


@dataclass(frozen=True)
class StoredSource:
    id: str
    kind: str
    host: str | None
    port: int | None
    database: str | None
    schema: str | None
    username: str | None
    tls_mode: str
    has_ca: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class StoredTable:
    source_id: str
    name: str
    kind: str
    selected: bool
    mode: str
    proposed_mode: str
    reason: str
    row_estimate: int | None
    size_bytes: int | None
    columns: tuple[CatalogColumn, ...]
    primary_key: tuple[str, ...]
    foreign_keys: tuple[ForeignKey, ...]
    unusual_columns: tuple[str, ...]
    interval_seconds: int
    cursor_column: str | None
    cursor_value: str | None
    next_run_at: str | None
    last_synced_at: str | None
    last_rows: int | None


@dataclass(frozen=True)
class TableChange:
    """A change to one table; a field left unset keeps its value, ``cursor_column=None`` clears the cursor."""

    name: str
    selected: bool | None = None
    mode: str | None = None
    interval_seconds: int | None = None
    cursor_column: str | None | _Unset = field(default=UNSET)


@dataclass(frozen=True)
class SyncRecord:
    id: int
    source_id: str
    started_by: str
    status: str
    started_at: str
    finished_at: str | None
    results: list
    error: str | None
    query_id: str | None


@dataclass(frozen=True)
class StoredFile:
    """An uploaded file: waiting for its types to be confirmed (``source_id`` is None) or the original of a source."""

    id: str
    source_id: str | None
    file_name: str
    format: str
    size_bytes: int
    sha256: str
    columns: tuple[tuple[str, str], ...]
    stored_path: str
    uploaded_by: str | None
    created_at: str


@dataclass(frozen=True)
class Claim:
    source_id: str
    sync_id: int
    tables: list[str]


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


_TABLE_COLUMNS = (
    "source_id, name, kind, selected, mode, proposed_mode, reason, row_estimate, size_bytes, columns, primary_key, "
    "foreign_keys, unusual_columns, interval_seconds, cursor_column, cursor_value, next_run_at, last_synced_at, last_rows"
)
_SYNC_COLUMNS = "id, source_id, started_by, status, started_at, finished_at, results, error, query_id"


def _table(row) -> StoredTable:
    return StoredTable(
        source_id=row[0], name=row[1], kind=row[2], selected=bool(row[3]), mode=row[4], proposed_mode=row[5],
        reason=row[6], row_estimate=row[7], size_bytes=row[8],
        columns=tuple(CatalogColumn(c["name"], c["type"], c["nullable"], c["position"]) for c in json.loads(row[9])),
        primary_key=tuple(json.loads(row[10])),
        foreign_keys=tuple(ForeignKey(tuple(k["columns"]), k["ref_table"], tuple(k["ref_columns"]))
                           for k in json.loads(row[11])),
        unusual_columns=tuple(json.loads(row[12])), interval_seconds=row[13], cursor_column=row[14],
        cursor_value=row[15], next_run_at=row[16], last_synced_at=row[17], last_rows=row[18],
    )


def _sync(row) -> SyncRecord:
    return SyncRecord(id=row[0], source_id=row[1], started_by=row[2], status=row[3], started_at=row[4],
                      finished_at=row[5], results=json.loads(row[6]), error=row[7], query_id=row[8])


class SourceStore:
    def __init__(self, db: StateDb):
        self._db = db

    # Sources

    def create(self, source: NewSource) -> StoredSource:
        if not valid_name(source.id):
            raise ValueError(f"{source.id!r} is not a valid source name")
        now = _iso(datetime.now(UTC))
        try:
            with self._db.write() as conn:
                conn.execute(
                    "INSERT INTO sources (id, kind, host, port, database, schema, username, tls_mode, has_ca, "
                    "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (source.id, source.kind, source.host, source.port, source.database, source.schema,
                     source.username, source.tls_mode, int(source.has_ca), now, now),
                )
        except sqlite3.IntegrityError:
            raise DuplicateSource(f"a source named {source.id!r} already exists") from None
        return self.get(source.id)

    @staticmethod
    def _source(row) -> StoredSource:
        return StoredSource(row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], bool(row[8]), row[9], row[10])

    _SOURCE_COLUMNS = "id, kind, host, port, database, schema, username, tls_mode, has_ca, created_at, updated_at"

    def get(self, source_id: str) -> StoredSource:
        row = self._db.connection().execute(
            f"SELECT {self._SOURCE_COLUMNS} FROM sources WHERE id = ?", (source_id,)).fetchone()
        if row is None:
            raise SourceNotFound(f"no source {source_id!r}")
        return self._source(row)

    def list(self) -> list[StoredSource]:
        rows = self._db.connection().execute(
            f"SELECT {self._SOURCE_COLUMNS} FROM sources ORDER BY created_at, id").fetchall()
        return [self._source(row) for row in rows]

    def update(self, source_id: str, **fields) -> StoredSource:
        allowed = {"host", "port", "database", "schema", "username", "tls_mode", "has_ca"}
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"cannot change {sorted(unknown)}")
        self.get(source_id)
        values = {key: int(value) if key == "has_ca" else value for key, value in fields.items()}
        assignments = ", ".join(f"{key} = ?" for key in [*values, "updated_at"])
        with self._db.write() as conn:
            conn.execute(f"UPDATE sources SET {assignments} WHERE id = ?",
                         (*values.values(), _iso(datetime.now(UTC)), source_id))
        return self.get(source_id)

    def delete(self, source_id: str) -> None:
        self.get(source_id)
        with self._db.write() as conn:
            conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))

    # Tables

    def tables(self, source_id: str) -> list[StoredTable]:
        rows = self._db.connection().execute(
            f"SELECT {_TABLE_COLUMNS} FROM source_tables WHERE source_id = ? ORDER BY name", (source_id,)).fetchall()
        return [_table(row) for row in rows]

    def save_catalog(self, source_id: str, tables: list[TableInfo]) -> None:
        """Store the catalog read from the source: new tables get the proposed mode, known ones keep their choices."""
        self.get(source_id)
        with self._db.write() as conn:
            names = [table.name for table in tables]
            conn.execute(
                f"DELETE FROM source_tables WHERE source_id = ? AND name NOT IN ({','.join('?' * len(names))})",
                (source_id, *names))
            for table in tables:
                proposal = propose(table)
                columns = json.dumps([{"name": c.name, "type": c.type, "nullable": c.nullable, "position": c.position}
                                      for c in table.columns])
                keys = json.dumps([{"columns": list(k.columns), "ref_table": k.ref_table,
                                    "ref_columns": list(k.ref_columns)} for k in table.foreign_keys])
                conn.execute(
                    "INSERT INTO source_tables (source_id, name, kind, mode, proposed_mode, reason, row_estimate, "
                    "size_bytes, columns, primary_key, foreign_keys, unusual_columns) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT (source_id, name) DO UPDATE SET kind = excluded.kind, "
                    "proposed_mode = excluded.proposed_mode, reason = excluded.reason, "
                    "row_estimate = excluded.row_estimate, size_bytes = excluded.size_bytes, "
                    "columns = excluded.columns, primary_key = excluded.primary_key, "
                    "foreign_keys = excluded.foreign_keys, unusual_columns = excluded.unusual_columns",
                    (source_id, table.name, table.kind, proposal.mode, proposal.mode, proposal.reason, table.rows,
                     table.size_bytes, columns, json.dumps(list(table.primary_key)), keys,
                     json.dumps(list(table.unusual_columns))))

    def set_tables(self, source_id: str, changes: list[TableChange]) -> None:
        """Apply every change or none; raises ``TableNotFound`` or ``ValueError`` for one that does not fit."""
        known = {table.name: table for table in self.tables(source_id)}
        for change in changes:
            table = known.get(change.name)
            if table is None:
                raise TableNotFound(f"the source has no table {change.name!r}")
            if change.mode is not None and change.mode not in MODES:
                raise ValueError(f"the mode must be one of {', '.join(MODES)}")
            if change.interval_seconds is not None and change.interval_seconds < MIN_INTERVAL_SECONDS:
                raise ValueError(f"the interval must be at least {MIN_INTERVAL_SECONDS} seconds")
            if isinstance(change.cursor_column, str) and change.cursor_column not in {c.name for c in table.columns}:
                raise ValueError(f"the cursor column {change.cursor_column!r} is not a column of {change.name!r}")
        with self._db.write() as conn:
            for change in changes:
                table = known[change.name]
                if change.selected is not None:
                    conn.execute("UPDATE source_tables SET selected = ? WHERE source_id = ? AND name = ?",
                                 (int(change.selected), source_id, change.name))
                if change.mode is not None:
                    conn.execute("UPDATE source_tables SET mode = ? WHERE source_id = ? AND name = ?",
                                 (change.mode, source_id, change.name))
                if change.interval_seconds is not None:
                    conn.execute("UPDATE source_tables SET interval_seconds = ? WHERE source_id = ? AND name = ?",
                                 (change.interval_seconds, source_id, change.name))
                if change.cursor_column is not UNSET and change.cursor_column != table.cursor_column:
                    conn.execute("UPDATE source_tables SET cursor_column = ?, cursor_value = NULL "
                                 "WHERE source_id = ? AND name = ?", (change.cursor_column, source_id, change.name))

    def record_table_sync(self, source_id: str, name: str, *, rows: int, cursor_value: str | None,
                          next_run_at: datetime, synced_at: datetime | None = None) -> None:
        with self._db.write() as conn:
            conn.execute(
                "UPDATE source_tables SET last_rows = ?, last_synced_at = ?, next_run_at = ?, "
                "cursor_value = COALESCE(?, cursor_value) WHERE source_id = ? AND name = ?",
                (rows, _iso(synced_at or datetime.now(UTC)), _iso(next_run_at), cursor_value, source_id, name))

    def defer_table(self, source_id: str, name: str, next_run_at: datetime) -> None:
        """Try the table again at ``next_run_at`` without touching its copy, its cursor or its last result."""
        with self._db.write() as conn:
            conn.execute("UPDATE source_tables SET next_run_at = ? WHERE source_id = ? AND name = ?",
                         (_iso(next_run_at), source_id, name))

    # Uploaded files

    _FILE_COLUMNS = "id, source_id, file_name, format, size_bytes, sha256, columns, stored_path, uploaded_by, created_at"

    @staticmethod
    def _file(row) -> StoredFile:
        return StoredFile(row[0], row[1], row[2], row[3], row[4], row[5],
                          tuple((c["name"], c["type"]) for c in json.loads(row[6])), row[7], row[8], row[9])

    def add_file(self, file: StoredFile) -> None:
        with self._db.write() as conn:
            conn.execute(
                f"INSERT INTO source_files ({self._FILE_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (file.id, file.source_id, file.file_name, file.format, file.size_bytes, file.sha256,
                 json.dumps([{"name": n, "type": t} for n, t in file.columns]), file.stored_path, file.uploaded_by,
                 file.created_at))

    def get_file(self, file_id: str) -> StoredFile | None:
        row = self._db.connection().execute(
            f"SELECT {self._FILE_COLUMNS} FROM source_files WHERE id = ?", (file_id,)).fetchone()
        return None if row is None else self._file(row)

    def file_of_source(self, source_id: str) -> StoredFile | None:
        row = self._db.connection().execute(
            f"SELECT {self._FILE_COLUMNS} FROM source_files WHERE source_id = ?", (source_id,)).fetchone()
        return None if row is None else self._file(row)

    def attach_file(self, file_id: str, source_id: str, columns: tuple[tuple[str, str], ...]) -> None:
        """Link an upload to its source and keep the column types the user confirmed."""
        with self._db.write() as conn:
            conn.execute("UPDATE source_files SET source_id = ?, columns = ? WHERE id = ?",
                         (source_id, json.dumps([{"name": n, "type": t} for n, t in columns]), file_id))

    # Syncs

    def _insert_running(self, conn, source_id: str, started_by: str, now: datetime) -> int:
        return conn.execute(
            "INSERT INTO source_syncs (source_id, started_by, status, started_at, heartbeat_at) "
            "VALUES (?, ?, 'running', ?, ?)", (source_id, started_by, _iso(now), _iso(now))).lastrowid

    def start_sync(self, source_id: str, started_by: str, now: datetime) -> SyncRecord:
        if started_by not in STARTERS:
            raise ValueError(f"unknown starter {started_by!r}")
        self.get(source_id)
        try:
            with self._db.write() as conn:
                self._mark_stale(conn, now)
                sync_id = self._insert_running(conn, source_id, started_by, now)
        except sqlite3.IntegrityError:
            raise SyncBusy(f"a sync of {source_id!r} is already running") from None
        return self.sync(sync_id)

    def sync(self, sync_id: int) -> SyncRecord:
        row = self._db.connection().execute(
            f"SELECT {_SYNC_COLUMNS} FROM source_syncs WHERE id = ?", (sync_id,)).fetchone()
        return _sync(row)

    def finish_sync(self, sync_id: int, status: str, *, results: list, error: str | None, finished_at: datetime) -> None:
        with self._db.write() as conn:
            conn.execute("UPDATE source_syncs SET status = ?, results = ?, error = ?, finished_at = ? WHERE id = ?",
                         (status, json.dumps(results), error, _iso(finished_at), sync_id))

    def touch_sync(self, sync_id: int, now: datetime) -> None:
        with self._db.write() as conn:
            conn.execute("UPDATE source_syncs SET heartbeat_at = ? WHERE id = ? AND status = 'running'",
                         (_iso(now), sync_id))

    def set_query_id(self, sync_id: int, query_id: str | None) -> None:
        with self._db.write() as conn:
            conn.execute("UPDATE source_syncs SET query_id = ? WHERE id = ?", (query_id, sync_id))

    def syncs(self, source_id: str, limit: int = 20) -> list[SyncRecord]:
        rows = self._db.connection().execute(
            f"SELECT {_SYNC_COLUMNS} FROM source_syncs WHERE source_id = ? ORDER BY id DESC LIMIT ?",
            (source_id, limit)).fetchall()
        return [_sync(row) for row in rows]

    def running(self, source_id: str) -> SyncRecord | None:
        row = self._db.connection().execute(
            f"SELECT {_SYNC_COLUMNS} FROM source_syncs WHERE source_id = ? AND status = 'running'",
            (source_id,)).fetchone()
        return None if row is None else _sync(row)

    @staticmethod
    def _mark_stale(conn, now: datetime) -> int:
        return conn.execute(
            "UPDATE source_syncs SET status = 'failed', error = 'interrupted', finished_at = ? "
            "WHERE status = 'running' AND heartbeat_at < ?", (_iso(now), _iso(now - STALE_AFTER))).rowcount

    def recover_interrupted(self, now: datetime) -> int:
        with self._db.write() as conn:
            return self._mark_stale(conn, now)

    def claim_due(self, now: datetime) -> list[Claim]:
        """Start a sync for every source with a selected copy table that is due; sources already syncing are skipped."""
        claims: list[Claim] = []
        with self._db.write() as conn:
            self._mark_stale(conn, now)
            rows = conn.execute(
                "SELECT t.source_id, t.name FROM source_tables AS t INNER JOIN sources AS s ON s.id = t.source_id "
                "WHERE t.selected = 1 AND t.mode = 'copy' AND s.kind != 'file' "
                "AND (t.next_run_at IS NULL OR t.next_run_at <= ?) "
                "AND NOT EXISTS (SELECT 1 FROM source_syncs AS y WHERE y.source_id = t.source_id AND y.status = 'running') "
                "ORDER BY t.source_id, t.name", (_iso(now),)).fetchall()
            due: dict[str, list[str]] = {}
            for source_id, name in rows:
                due.setdefault(source_id, []).append(name)
            for source_id, names in due.items():
                claims.append(Claim(source_id, self._insert_running(conn, source_id, "schedule", now), names))
        return claims
