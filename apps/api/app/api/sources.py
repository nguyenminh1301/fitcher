"""The Sources page and the setup's Data step: connect, test, edit, delete and sync sources (DECISIONS §4, §15).

Only an ``admin`` reaches these endpoints, and in individual mode the owner holds that role. A password is sent
once, when a source is connected or its password replaced, and goes straight into the source's ClickHouse named
collection: no response, log line or admin action carries it, and a failure is answered with one fixed reason
instead of the driver's text. A source is saved only after its connection was tested.
"""

from datetime import datetime
import json
import logging
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status

from app.api.console import require_admin
from app.api.runtime import get_admin_action_log, get_file_service, get_source_service, get_source_store, unavailable
from app.auth.principal import Principal
from app.contracts.sources import (
    ColumnView, FileColumn, FileLoad, FileUploadView, ForeignKeyView, ProbeResult, SourceConnection, SourceCreate, SourceDetail, SourcePatch, SourceView,
    SyncView, TableChangeInput, TablesChange, TableView,
)
from app.observability.events import AdminActionRecord, utc_now
from app.onboarding.docs_parser import DocumentRejected
from app.sources.attach import valid_name
from app.sources.collections import CollectionError
from app.sources import files as source_files
from app.sources.connection import DEFAULT_PORTS, Connection, ConnectionFieldError
from app.sources.files import FileService
from app.sources.inspect import InspectError, TableInfo
from app.sources.modes import cursor_candidates, joined_live_tables, propose
from app.sources.service import ConnectionPatch, SourceInUse, SourceService
from app.sources.store import (
    DuplicateSource, SourceNotFound, SourceStore, StoredSource, StoredTable, SyncBusy, SyncRecord, TableChange,
    TableNotFound, UNSET,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sources")
Admin = Annotated[Principal, Depends(require_admin)]
Store = Annotated[SourceStore, Depends(get_source_store)]
Service = Annotated[SourceService, Depends(get_source_service)]


class ActionLog(Protocol):
    def record_action(self, record: AdminActionRecord) -> None: ...


Log = Annotated[ActionLog, Depends(get_admin_action_log)]
Files = Annotated[FileService, Depends(get_file_service)]


def _record(log: ActionLog, admin: Principal, action: str, target: str, old: str, new: str) -> None:
    try:
        log.record_action(AdminActionRecord(ts=utc_now(), actor=admin.user_id, action=action, target=target,
                                            old_value=old, new_value=new))
    except Exception:  # noqa: BLE001 - the change already happened
        logger.exception("the admin action %s on %s was not recorded", action, target)


def _described(source: StoredSource | None, password_changed: bool = False) -> str:
    if source is None:
        return ""
    return json.dumps({"kind": source.kind, "host": source.host, "port": source.port, "database": source.database,
                       "schema": source.schema, "user": source.username, "tls_mode": source.tls_mode,
                       "password_changed": password_changed})


def _iso(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


def _connection(body: SourceConnection) -> Connection:
    return Connection(kind=body.kind, host=body.host, port=body.port or DEFAULT_PORTS[body.kind],
                      database=body.database, user=body.user, password=body.password, schema=body.schema_name,
                      tls_mode=body.tls_mode, ca_certificate=body.ca_certificate or None)


def _column_views(columns) -> list[ColumnView]:
    return [ColumnView(name=c.name, type=c.type, nullable=c.nullable) for c in columns]


def _keys(keys) -> list[ForeignKeyView]:
    return [ForeignKeyView(columns=list(k.columns), ref_table=k.ref_table, ref_columns=list(k.ref_columns)) for k in keys]


def _table_view(table: StoredTable, slow: set[str]) -> TableView:
    return TableView(
        name=table.name, kind=table.kind, rows=table.row_estimate, size_bytes=table.size_bytes,
        columns=_column_views(table.columns), primary_key=list(table.primary_key),
        foreign_keys=_keys(table.foreign_keys), unusual_columns=list(table.unusual_columns), selected=table.selected,
        mode=table.mode, proposed_mode=table.proposed_mode, reason=table.reason, slow=table.name in slow,
        interval_seconds=table.interval_seconds, cursor_column=table.cursor_column,
        cursor_candidates=cursor_candidates(table.columns), last_synced_at=_iso(table.last_synced_at),
        last_rows=table.last_rows, next_run_at=_iso(table.next_run_at),
    )


def _probe_view(table: TableInfo) -> TableView:
    proposal = propose(table)
    return TableView(
        name=table.name, kind=table.kind, rows=table.rows, size_bytes=table.size_bytes,
        columns=_column_views(table.columns), primary_key=list(table.primary_key),
        foreign_keys=_keys(table.foreign_keys), unusual_columns=list(table.unusual_columns), selected=False,
        mode=proposal.mode, proposed_mode=proposal.mode, reason=proposal.reason, slow=False, interval_seconds=86_400,
        cursor_column=None, cursor_candidates=cursor_candidates(table.columns), last_synced_at=None, last_rows=None,
        next_run_at=None,
    )


def _table_views(tables: list[StoredTable]) -> list[TableView]:
    slow = joined_live_tables(tables, {t.name: t.mode for t in tables if t.selected})
    return [_table_view(table, slow) for table in tables]


def _sync_view(sync: SyncRecord) -> SyncView:
    return SyncView(id=sync.id, status=sync.status, started_by=sync.started_by, started_at=datetime.fromisoformat(sync.started_at),
                    finished_at=_iso(sync.finished_at), results=sync.results, error=sync.error)


def _source_view(source: StoredSource, store: SourceStore) -> SourceView:
    tables = store.tables(source.id)
    syncs = store.syncs(source.id, limit=1)
    return SourceView(
        id=source.id, kind=source.kind, host=source.host, port=source.port, database=source.database,
        schema_name=source.schema, user=source.username, tls_mode=source.tls_mode, has_ca=source.has_ca,
        created_at=datetime.fromisoformat(source.created_at), table_count=len(tables),
        selected_count=sum(1 for table in tables if table.selected),
        last_sync=_sync_view(syncs[0]) if syncs else None,
    )


def _detail(source: StoredSource, store: SourceStore) -> SourceDetail:
    return SourceDetail(**_source_view(source, store).model_dump(), tables=_table_views(store.tables(source.id)))


def _refusal(error: Exception) -> HTTPException:
    """The HTTP answer for a failed source change; the detail never carries a driver message."""
    if isinstance(error, InspectError):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"reason": error.reason})
    if isinstance(error, (DuplicateSource, SyncBusy)):
        return HTTPException(status.HTTP_409_CONFLICT, detail=str(error))
    if isinstance(error, SourceInUse):
        return HTTPException(status.HTTP_409_CONFLICT, detail={"message": str(error), "marts": error.marts})
    if isinstance(error, (SourceNotFound, TableNotFound)):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=str(error))
    if isinstance(error, source_files.FileTooLarge):
        return HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, detail=str(error))
    if isinstance(error, DocumentRejected):
        return HTTPException(error.status, detail=str(error))
    if isinstance(error, source_files.UploadNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=str(error))
    if isinstance(error, source_files.LoadFailed):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error))
    if isinstance(error, (ValueError, ConnectionFieldError)):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error))
    if isinstance(error, CollectionError):
        logger.error("a source's named collection could not be changed: %s", error.reason)
        return unavailable("ClickHouse could not store the connection; check that source_admin is configured")
    logger.error("a source request failed", exc_info=error)
    return unavailable("ClickHouse or the app state is unavailable")


def _found(store: SourceStore, source_id: str) -> StoredSource:
    try:
        return store.get(source_id)
    except SourceNotFound as error:
        raise _refusal(error) from None


@router.post("/files", status_code=status.HTTP_201_CREATED)
def upload_file(admin: Admin, service: Files, file: Annotated[UploadFile, File()]) -> FileUploadView:
    try:
        upload = service.upload(file.filename or "data", file.file, admin.user_id)
    except Exception as error:  # noqa: BLE001 - each failure maps to its status in _refusal
        raise _refusal(error) from None
    return FileUploadView(
        id=upload.id, file_name=upload.file_name, format=upload.format, size_bytes=upload.size_bytes,
        columns=[FileColumn(name=c.name, type=c.type) for c in upload.columns], sample=upload.sample)


@router.post("/files/{file_id}/load", status_code=status.HTTP_201_CREATED)
def load_file(file_id: str, body: FileLoad, admin: Admin, service: Files, store: Store, log: Log) -> SourceDetail:
    try:
        source = service.load(file_id, body.name, [source_files.FileColumn(c.name, c.type) for c in body.columns])
    except Exception as error:  # noqa: BLE001 - each failure maps to its status in _refusal
        raise _refusal(error) from None
    _record(log, admin, "source_add", source.id, "", _described(source))
    return _detail(source, store)


@router.get("")
def list_sources(_: Admin, store: Store) -> list[SourceView]:
    return [_source_view(source, store) for source in store.list()]


@router.post("/test")
def test_connection(body: SourceConnection, _: Admin, service: Service) -> ProbeResult:
    try:
        return ProbeResult(tables=[_probe_view(table) for table in service.probe(_connection(body))])
    except Exception as error:  # noqa: BLE001 - each failure maps to its status in _refusal
        raise _refusal(error) from None


@router.post("", status_code=status.HTTP_201_CREATED)
def create_source(body: SourceCreate, admin: Admin, store: Store, service: Service, log: Log) -> SourceDetail:
    if not valid_name(body.name):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            detail="the name must be lower-case letters, digits and underscores, starting with a letter")
    try:
        source, _ = service.create(body.name, _connection(body))
    except Exception as error:  # noqa: BLE001 - each failure maps to its status in _refusal
        raise _refusal(error) from None
    _record(log, admin, "source_add", source.id, "", _described(source))
    return _detail(source, store)


@router.patch("/{source_id}")
def edit_source(source_id: str, body: SourcePatch, admin: Admin, store: Store, service: Service, log: Log) -> SourceDetail:
    before = _found(store, source_id)
    patch = ConnectionPatch(host=body.host, port=body.port, database=body.database, schema=body.schema_name,
                            user=body.user, password=body.password, tls_mode=body.tls_mode,
                            ca_certificate=body.ca_certificate)
    try:
        after, _ = service.update(source_id, patch)
    except Exception as error:  # noqa: BLE001 - each failure maps to its status in _refusal
        raise _refusal(error) from None
    _record(log, admin, "source_edit", source_id, _described(before),
            _described(after, password_changed=body.password is not None))
    return _detail(after, store)


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_source(source_id: str, admin: Admin, store: Store, service: Service, log: Log,
                  confirm: str | None = None) -> Response:
    before = _found(store, source_id)
    try:
        service.delete(source_id, confirm or "")
    except Exception as error:  # noqa: BLE001 - each failure maps to its status in _refusal
        raise _refusal(error) from None
    _record(log, admin, "source_delete", source_id, _described(before), "")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{source_id}/tables")
def list_tables(source_id: str, _: Admin, store: Store, service: Service, refresh: bool = False) -> list[TableView]:
    _found(store, source_id)
    try:
        tables = service.refresh(source_id) if refresh else store.tables(source_id)
    except Exception as error:  # noqa: BLE001 - each failure maps to its status in _refusal
        raise _refusal(error) from None
    return _table_views(tables)


def _change(item: TableChangeInput, sent: set[str]) -> TableChange:
    return TableChange(name=item.name, selected=item.selected, mode=item.mode, interval_seconds=item.interval_seconds,
                       cursor_column=item.cursor_column if "cursor_column" in sent else UNSET)


@router.put("/{source_id}/tables")
def change_tables(source_id: str, body: TablesChange, _: Admin, store: Store) -> list[TableView]:
    _found(store, source_id)
    try:
        store.set_tables(source_id, [_change(item, item.model_fields_set) for item in body.tables])
    except (ValueError, TableNotFound) as error:
        raise _refusal(error) from None
    return _table_views(store.tables(source_id))


@router.post("/{source_id}/sync", status_code=status.HTTP_202_ACCEPTED)
def start_sync(source_id: str, _: Admin, store: Store, service: Service) -> SyncView:
    _found(store, source_id)
    try:
        return _sync_view(service.start(source_id, "manual"))
    except Exception as error:  # noqa: BLE001 - each failure maps to its status in _refusal
        raise _refusal(error) from None


@router.post("/{source_id}/sync/cancel")
def cancel_sync(source_id: str, _: Admin, store: Store, service: Service) -> SyncView:
    _found(store, source_id)
    running = store.running(source_id)
    try:
        if running is None or not service.cancel(source_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="no sync is running")
    except HTTPException:
        raise
    except Exception as error:  # noqa: BLE001 - each failure maps to its status in _refusal
        raise _refusal(error) from None
    return _sync_view(running)


@router.get("/{source_id}/syncs")
def list_syncs(source_id: str, _: Admin, store: Store) -> list[SyncView]:
    _found(store, source_id)
    return [_sync_view(sync) for sync in store.syncs(source_id)]
