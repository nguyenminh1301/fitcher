"""The console's Documents page: upload, list, retag and delete company documents (DECISIONS §5, §15).

Only a ``pack_reviewer`` reaches these endpoints. An upload is a multipart
form with ``file`` and one ``allowed_roles`` field per role; the body is read
at most one byte past the size cap. Uploads, retags and deletes answer 409
while the pack compiles, and an upload whose content is already registered
for the pack is 409 as well. ``POST /documents/{id}/draft`` drafts pack items
from one indexed document's chunks and the pack's profile; it sends billable
``sql-gen`` calls, so the page asks for confirmation first.

While an admin has turned documents off (``/settings/documents``), every
``/documents`` endpoint answers 404; the stored files and the registry are
kept, and turning documents on again indexes them at the next compile.
"""

import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status

from app.api.auth import current_principal
from app.api.console import require_admin, require_reviewer
from app.api.runtime import (
    get_document_service, get_document_service_or_none, get_drafter, get_pack_dir, get_state_db, unavailable,
)
from app.auth.principal import Principal
from app.contracts.documents import (
    DocumentList, DocumentRolesChange, DocumentSettings, DocumentSettingsChange, DocumentView, DraftResult,
)
from app.llm.client import LLMError
from app.observability.tracing import trusted_pack_calls
from app.onboarding.docs_parser import DocumentRejected
from app.onboarding.documents import (
    DocumentNotFound, DocumentRecord, DocumentService, DuplicateDocument, PackCompiling,
)
from app.onboarding.drafter import Drafter, DraftError, draft_files
from app.onboarding.pack_yaml import PackFiles
from app.onboarding.profiler import read_profile
from app.packs.loader import PackValidationError
from app.state.db import StateDb
from app.state.settings import Settings, documents_enabled

logger = logging.getLogger(__name__)
State = Annotated[StateDb, Depends(get_state_db)]


def require_documents_on(db: State) -> None:
    if not documents_enabled(db):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="company documents are turned off")


router = APIRouter(prefix="/documents", dependencies=[Depends(require_documents_on)])
settings_router = APIRouter(prefix="/settings/documents")
Reviewer = Annotated[Principal, Depends(require_reviewer)]
Service = Annotated[DocumentService, Depends(get_document_service)]


def view(record: DocumentRecord) -> DocumentView:
    return DocumentView(
        id=record.id, name=record.file_name, size=record.size_bytes, media_type=record.media_type,
        status=record.status, error=record.error, roles=record.allowed_roles, chunk_count=record.chunk_count,
        blocked_chunks=record.blocked_chunks, uploaded_by=record.uploaded_by, uploaded_at=record.uploaded_at,
    )


def refusal(error: Exception) -> HTTPException:
    """The HTTP answer for a failed document change; an unexpected failure is logged and answered 503."""
    if isinstance(error, DocumentRejected):
        return HTTPException(error.status, detail=str(error))
    if isinstance(error, (PackCompiling, DuplicateDocument)):
        return HTTPException(status.HTTP_409_CONFLICT, detail=str(error))
    if isinstance(error, DocumentNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail="document not found")
    logger.error("a document change failed", exc_info=error)
    return unavailable("the document store, search index or embedding model is unavailable")


@router.get("")
def list_documents(_: Reviewer, service: Service) -> DocumentList:
    try:
        records = service.list()
    except Exception as error:  # noqa: BLE001 - the registry is unreachable
        raise refusal(error) from None
    return DocumentList(compiling=service.compiling(), documents=[view(record) for record in records])


@router.post("", status_code=status.HTTP_201_CREATED)
def upload_document(
    reviewer: Reviewer,
    service: Service,
    file: Annotated[UploadFile, File()],
    allowed_roles: Annotated[list[str] | None, Form()] = None,
) -> DocumentView:
    data = file.file.read(service.max_bytes + 1)
    try:
        return view(service.upload(file.filename or "document", data, allowed_roles or [], reviewer.user_id))
    except Exception as error:  # noqa: BLE001 - each failure maps to its status in refusal
        raise refusal(error) from None


@router.patch("/{document_id}")
def change_roles(document_id: str, body: DocumentRolesChange, _: Reviewer, service: Service) -> DocumentView:
    try:
        return view(service.set_roles(document_id, body.allowed_roles))
    except Exception as error:  # noqa: BLE001 - each failure maps to its status in refusal
        raise refusal(error) from None


@router.post("/{document_id}/draft")
def draft_from_document(
    document_id: str,
    _: Reviewer,
    service: Service,
    drafter: Annotated[Drafter, Depends(get_drafter)],
    pack_dir: Annotated[Path, Depends(get_pack_dir)],
) -> DraftResult:
    record = service.registry.get(service.pack, document_id)
    if record is None or record.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="document not found")
    if record.status != "indexed":
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"the document is {record.status}, not indexed")
    try:
        chunks = service.chunks(document_id)
        with trusted_pack_calls():
            results = draft_files(drafter, PackFiles(pack_dir), read_profile(service.compiled_dir, service.pack), chunks)
    except PackValidationError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from None
    except (DraftError, LLMError) as error:
        raise unavailable(f"drafting failed: {error}") from None
    except Exception as error:  # noqa: BLE001 - search or ClickHouse unreachable
        raise refusal(error) from None

    def ids(kind: str) -> list[str]:
        return [f"{file.removesuffix('.yaml')}.{item}" for file, result in results.items() for item in getattr(result, kind)]

    return DraftResult(added=ids("added"), updated=ids("updated"), skipped_approved=ids("skipped_approved"))


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: str, _: Reviewer, service: Service) -> Response:
    try:
        service.delete(document_id)
    except Exception as error:  # noqa: BLE001 - each failure maps to its status in refusal
        raise refusal(error) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


OptionalService = Annotated[DocumentService | None, Depends(get_document_service_or_none)]


def _kept_documents(service: DocumentService | None) -> int | None:
    """The active pack's kept documents, 0 without an active pack, or None when the registry cannot be read."""
    if service is None:
        return 0
    try:
        return len(service.list())
    except Exception:  # noqa: BLE001 - the registry is unreachable
        logger.warning("the document registry could not be read", exc_info=True)
        return None


@settings_router.get("")
def get_document_settings(
    _: Annotated[Principal, Depends(current_principal)], db: State, service: OptionalService,
) -> DocumentSettings:
    return DocumentSettings(enabled=documents_enabled(db), documents=_kept_documents(service) or 0)


@settings_router.put("")
def put_document_settings(
    change: DocumentSettingsChange, _: Annotated[Principal, Depends(require_admin)], db: State, service: OptionalService,
) -> DocumentSettings:
    """Turn documents on or off; off with documents kept needs ``confirm``."""
    kept = _kept_documents(service)
    if not change.enabled and documents_enabled(db) and not change.confirm and kept != 0:
        held = "the documents" if kept is None else f"{kept} document{'s' if kept != 1 else ''}"
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"{held} stay stored but are no longer searched; confirm to turn company documents off",
        )
    Settings(db).set("documents", "enabled", change.enabled)
    return DocumentSettings(enabled=change.enabled, documents=kept or 0)
