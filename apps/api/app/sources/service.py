"""Connect, edit, delete and sync sources: the code that joins the store, ClickHouse and the source's catalog.

Every ClickHouse statement runs as ``source_admin``. A source's password is written once into its named
collection and kept nowhere else; a test never leaves a collection behind, and a source is saved only after its
connection was tested (DECISIONS §4, §15).

A sync runs inside the api process but waits on ClickHouse: a copy is an ``INSERT ... SELECT`` there, tagged with
a query id that ``cancel`` kills. A running sync touches a heartbeat so that a process that died is recognised.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
import re
import secrets
import threading

from app.sources.attach import RAW_DATABASE, Source, Table, attach_live, copy_table, drop_source, valid_name
from app.sources.collections import CollectionAdmin, CollectionError, ca_key
from app.sources.connection import COPY_ONLY_KINDS, Connection, validate
from app.sources.inspect import InspectError, Inspector, TableInfo, classify_error
from app.sources.store import (
    DuplicateSource, NewSource, SourceStore, StoredSource, StoredTable, SyncBusy, SyncRecord,
)

PROBE_PREFIX = "probe_"
HEARTBEAT_SECONDS = 30


class SourceInUse(RuntimeError):
    """A mart of the pack reads the source, so it cannot be deleted."""

    def __init__(self, marts: list[str]):
        super().__init__(f"the marts {', '.join(marts)} read this source")
        self.marts = marts


@dataclass(frozen=True)
class ConnectionPatch:
    """The fields of an edit; ``None`` keeps a value, and an empty ``ca_certificate`` removes the stored one."""

    host: str | None = None
    port: int | None = None
    database: str | None = None
    schema: str | None = None
    user: str | None = None
    password: str | None = None
    tls_mode: str | None = None
    ca_certificate: str | None = None


class _Tracked:
    """A ClickHouse client that tags each command of one sync with a query id the sync can be cancelled by."""

    def __init__(self, client, record: Callable[[str], None], base: str):
        self._client, self._record, self._base, self._count = client, record, base, 0

    def command(self, sql, **kwargs):
        self._count += 1
        query_id = f"{self._base}-{self._count}"
        self._record(query_id)
        return self._client.command(sql, settings={**(kwargs.pop("settings", None) or {}), "query_id": query_id}, **kwargs)

    def query(self, sql, **kwargs):
        return self._client.query(sql, **kwargs)


class SourceService:
    def __init__(self, store: SourceStore, client, clock: Callable[[], datetime] = lambda: datetime.now(UTC),
                 files=None, sqlserver=None, vault=None):
        self._store = store
        self._client = client
        self._clock = clock
        # Reloads the stored original of a file source; without it a file source cannot be synced.
        self._files = files
        # SQL Server is read by the api itself and its password is a secret of the app state (app/sources/sqlserver.py).
        self._sqlserver = sqlserver
        self._vault = vault
        self._collections = CollectionAdmin(client)
        self._inspector = Inspector(client)
        self._cancelled: set[int] = set()

    # SQL Server: no named collection, the password lives in the vault

    @staticmethod
    def _password_name(source_id: str) -> str:
        return f"source:{source_id}:password"

    @staticmethod
    def _login(connection: Connection) -> dict:
        return {"host": connection.host, "port": connection.port, "database": connection.database,
                "user": connection.user, "password": connection.password, "tls_mode": connection.tls_mode}

    def _login_of(self, stored: StoredSource) -> dict:
        """The stored login of a SQL Server source with its password from the vault."""
        return {"host": stored.host, "port": stored.port, "database": stored.database, "user": stored.username,
                "password": self._vault.reader().get(self._password_name(stored.id)), "tls_mode": stored.tls_mode}

    def _sqlserver_tables(self, login: dict, schema: str) -> list[TableInfo]:
        self._sqlserver.check(**login)
        return self._sqlserver.tables(schema=schema, **login)

    # Connections

    @staticmethod
    def _source(name: str, connection: Connection) -> Source:
        return Source(name=name, kind=connection.kind, database=connection.database, schema=connection.schema)

    def probe(self, connection: Connection) -> list[TableInfo]:
        """Test a connection and list its tables through a collection that exists only for the test."""
        connection = validate(connection)
        if connection.kind in COPY_ONLY_KINDS:
            return self._sqlserver_tables(self._login(connection), connection.schema)
        name = PROBE_PREFIX + secrets.token_hex(6)
        self._collections.create(name, connection)
        try:
            source = self._source(name, connection)
            self._inspector.check(source)
            return self._inspector.tables(source)
        finally:
            self._drop_quietly(name)

    def _drop_quietly(self, name: str) -> None:
        try:
            self._collections.drop(name)
        except CollectionError:
            pass

    def create(self, name: str, connection: Connection) -> tuple[StoredSource, list[StoredTable]]:
        if not valid_name(name) or name.startswith(PROBE_PREFIX):
            raise ValueError(f"{name!r} is not a valid source name: use lower-case letters, digits and underscores")
        connection = validate(connection)
        if any(source.id == name for source in self._store.list()):
            raise DuplicateSource(f"a source named {name!r} already exists")
        if connection.kind in COPY_ONLY_KINDS:
            return self._create_copy_only(name, connection)
        try:
            self._collections.create(name, connection)
        except CollectionError as error:
            if error.reason == "name_taken":
                raise DuplicateSource(f"the name {name!r} is already used by a connection of the server") from None
            raise
        try:
            source = self._source(name, connection)
            self._inspector.check(source)
            tables = self._inspector.tables(source)
            stored = self._store.create(NewSource(
                id=name, kind=connection.kind, host=connection.host, port=connection.port,
                database=connection.database, schema=connection.schema, username=connection.user,
                tls_mode=connection.tls_mode, has_ca=bool(connection.ca_certificate)))
            self._store.save_catalog(name, tables)
        except BaseException:
            self._drop_quietly(name)
            raise
        return stored, self._store.tables(name)

    def _create_copy_only(self, name: str, connection: Connection) -> tuple[StoredSource, list[StoredTable]]:
        tables = self._sqlserver_tables(self._login(connection), connection.schema)
        self._vault.set(self._password_name(name), connection.password)
        try:
            stored = self._store.create(NewSource(
                id=name, kind=connection.kind, host=connection.host, port=connection.port,
                database=connection.database, schema=connection.schema, username=connection.user,
                tls_mode=connection.tls_mode, has_ca=False))
            self._store.save_catalog(name, tables)
        except BaseException:
            self._vault.delete(self._password_name(name))
            raise
        return stored, self._store.tables(name)

    @staticmethod
    def _connection_of(stored: StoredSource) -> Connection:
        """The stored fields; the password and the CA certificate are not kept here, so both are ``None``."""
        return Connection(kind=stored.kind, host=stored.host, port=stored.port, database=stored.database,
                          user=stored.username, password=None, schema=stored.schema, tls_mode=stored.tls_mode)

    def update(self, source_id: str, patch: ConnectionPatch) -> tuple[StoredSource, list[StoredTable]]:
        stored = self._store.get(source_id)
        old = self._connection_of(stored)
        new = validate(replace(
            old, host=patch.host or old.host, port=patch.port or old.port, database=patch.database or old.database,
            schema=patch.schema if patch.schema is not None else old.schema, user=patch.user or old.user,
            tls_mode=patch.tls_mode or old.tls_mode, password=patch.password,
            ca_certificate=patch.ca_certificate or None))
        if new.kind in COPY_ONLY_KINDS:
            return self._update_copy_only(stored, new, patch.password)
        remove_ca = patch.ca_certificate == ""
        drop = [ca_key(new.kind)] if remove_ca else []
        has_ca = False if remove_ca else (True if patch.ca_certificate else stored.has_ca)
        if patch.password is not None or patch.ca_certificate:
            # A secret that replaces a stored one is tested on a collection of its own, because the old value
            # cannot be read back to restore it: the stored collection changes only once the new one works.
            probe = PROBE_PREFIX + secrets.token_hex(6)
            self._collections.create(probe, new)
            try:
                self._inspector.check(self._source(probe, new))
            finally:
                self._drop_quietly(probe)
            self._collections.replace(source_id, new, drop=drop)
        else:
            # Only fields the state knows change, so a failed test restores them exactly.
            self._collections.replace(source_id, new, drop=drop)
            try:
                self._inspector.check(self._source(source_id, new))
            except InspectError:
                self._collections.replace(source_id, old)
                raise
        updated = self._store.update(
            source_id, host=new.host, port=new.port, database=new.database, schema=new.schema, username=new.user,
            tls_mode=new.tls_mode, has_ca=has_ca)
        self._store.save_catalog(source_id, self._inspector.tables(self._source(source_id, new)))
        return updated, self._store.tables(source_id)

    def _update_copy_only(self, stored: StoredSource, new: Connection, password: str | None):
        """Test the edited login (with the new or the stored password) and only then replace what is stored."""
        login = {**self._login(new), "password": password if password is not None else self._login_of(stored)["password"]}
        tables = self._sqlserver_tables(login, new.schema)
        if password is not None:
            self._vault.set(self._password_name(stored.id), password)
        updated = self._store.update(stored.id, host=new.host, port=new.port, database=new.database,
                                     schema=new.schema, username=new.user, tls_mode=new.tls_mode, has_ca=False)
        self._store.save_catalog(stored.id, tables)
        return updated, self._store.tables(stored.id)

    def refresh(self, source_id: str) -> list[StoredTable]:
        stored = self._store.get(source_id)
        if stored.kind in COPY_ONLY_KINDS:
            self._store.save_catalog(source_id, self._sqlserver_tables(self._login_of(stored), stored.schema))
            return self._store.tables(source_id)
        self._store.save_catalog(source_id, self._inspector.tables(self._source(source_id, self._connection_of(stored))))
        return self._store.tables(source_id)

    # Deleting

    def marts_using(self, source_id: str) -> list[str]:
        """The marts whose definition reads the source's live database or its copies."""
        pattern = re.compile(rf"\bsrc_{re.escape(source_id)}\b|`?{RAW_DATABASE}`?\s*\.\s*`?{re.escape(source_id)}__")
        rows = self._client.query(
            "SELECT name, create_table_query FROM system.tables WHERE database = 'marts' ORDER BY name").result_rows
        return [name for name, definition in rows if pattern.search(definition)]

    def delete(self, source_id: str, confirm: str) -> None:
        if confirm != source_id:
            raise ValueError(f"confirm the deletion by sending the source name {source_id!r}")
        stored = self._store.get(source_id)
        marts = self.marts_using(source_id)
        if marts:
            raise SourceInUse(marts)
        if self._store.running(source_id) is not None:
            raise SyncBusy(f"a sync of {source_id!r} is running; cancel it first")
        tables = tuple(Table(table.name) for table in self._store.tables(source_id))
        drop_source(self._client, Source(source_id, stored.kind, tables))
        if stored.kind in COPY_ONLY_KINDS:
            self._vault.delete(self._password_name(source_id))
        else:
            self._collections.drop(source_id)
        self._store.delete(source_id)

    # Syncing

    def start(self, source_id: str, started_by: str, tables: list[str] | None = None) -> SyncRecord:
        """Claim the source and run its sync on a thread; raises ``SyncBusy`` while another sync runs."""
        record = self._claim(source_id, started_by)
        threading.Thread(target=self.run, args=(record, tables), name=f"sync-{source_id}", daemon=True).start()
        return record

    def _claim(self, source_id: str, started_by: str) -> SyncRecord:
        selected = [table for table in self._store.tables(source_id) if table.selected]
        if not selected:
            raise ValueError("the source has no selected table to sync")
        return self._store.start_sync(source_id, started_by, self._clock())

    def sync(self, source_id: str, started_by: str) -> SyncRecord:
        """Run a sync now and return its record."""
        return self.run(self._claim(source_id, started_by))

    def run(self, record: SyncRecord, only: list[str] | None = None) -> SyncRecord:
        stored = self._store.get(record.source_id)
        done = threading.Event()

        def beat() -> None:
            while not done.wait(HEARTBEAT_SECONDS):
                self._store.touch_sync(record.id, self._clock())

        threading.Thread(target=beat, name=f"heartbeat-{record.source_id}", daemon=True).start()
        client = _Tracked(self._client, lambda query_id: self._store.set_query_id(record.id, query_id),
                          f"fitcher-sync-{record.id}")
        selected = [t for t in self._store.tables(record.source_id) if t.selected and (only is None or t.name in only)]
        results: list[dict] = []
        status, error = "succeeded", None
        try:
            if stored.kind == "file":
                rows = self._files.reload(stored.id)
                self._store.record_table_sync(stored.id, stored.id, rows=rows, cursor_value=None,
                                              next_run_at=self._clock() + timedelta(days=36500), synced_at=self._clock())
                results.append({"table": stored.id, "mode": "copy", "rows": rows, "full": True})
                selected = []
            live = [t for t in selected if t.mode == "live"]
            if live:
                source = Source(stored.id, stored.kind, tuple(Table(t.name) for t in live),
                                database=stored.database, schema=stored.schema)
                counts = attach_live(client, source)
                results += [{"table": t.name, "mode": "live", "rows": counts[t.name], "full": None} for t in live]
            for table in (t for t in selected if t.mode == "copy"):
                results.append(self._copy(client, stored, table, record.id))
        except Exception as failure:  # noqa: BLE001 - only the reason is kept: the text can name hosts and users
            error = failure.reason if isinstance(failure, InspectError) else classify_error(failure)
            status = "failed"
            if record.id in self._cancelled or "QUERY_WAS_CANCELLED" in str(failure):
                status, error = "cancelled", None
            # The tables that did not finish keep their copy and are tried again after their interval.
            finished = {result["table"] for result in results}
            for table in (t for t in selected if t.mode == "copy" and t.name not in finished):
                self._store.defer_table(stored.id, table.name, self._clock() + timedelta(seconds=table.interval_seconds))
        finally:
            done.set()
            self._cancelled.discard(record.id)
            self._store.set_query_id(record.id, None)
        self._store.finish_sync(record.id, status, results=results, error=error, finished_at=self._clock())
        return self._store.sync(record.id)

    def _copy(self, client, stored: StoredSource, table: StoredTable, record_id: int) -> dict:
        source = Source(stored.id, stored.kind, (Table(table.name),), database=stored.database, schema=stored.schema)
        if stored.kind in COPY_ONLY_KINDS:
            outcome = self._sqlserver.copy(
                self._client, source, table.name, cursor_column=table.cursor_column, after=table.cursor_value,
                schema=stored.schema, should_stop=lambda: record_id in self._cancelled, **self._login_of(stored))
        else:
            outcome = copy_table(client, source, source.tables[0], cursor_column=table.cursor_column,
                                 after=table.cursor_value)
        self._store.record_table_sync(
            stored.id, table.name, rows=outcome.rows, cursor_value=outcome.cursor,
            next_run_at=self._clock() + timedelta(seconds=table.interval_seconds), synced_at=self._clock())
        return {"table": table.name, "mode": "copy", "rows": outcome.rows, "full": outcome.full}

    def cancel(self, source_id: str) -> bool:
        """Kill the running sync's query; the sync then ends as ``cancelled``."""
        running = self._store.running(source_id)
        if running is None:
            return False
        self._cancelled.add(running.id)
        if running.query_id:
            self._client.command(f"KILL QUERY WHERE query_id = '{running.query_id}'")
        return True
