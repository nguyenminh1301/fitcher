"""The console's Documents page: upload, list, retag and delete company documents (DECISIONS §5, §15).

Only a ``pack_reviewer`` reaches these endpoints. An upload is a multipart
form with ``file`` and one ``allowed_roles`` field per role; the body is read
at most one byte past the size cap. Uploads, retags and deletes answer 409
while the pack compiles, and an upload whose content is already registered
for the pack is 409 as well. ``POST /documents/{id}/draft`` drafts pack items
from one indexed document's chunks and the pack's profile; it sends billable
``sql-gen`` calls, so the page asks for confirmation first.
"""

import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status

from app.api.console import require_reviewer
from app.api.runtime import get_document_service, get_drafter, get_pack_dir, unavailable
from app.auth.jwt import Principal
from app.contracts.documents import DocumentList, DocumentRolesChange, DocumentView, DraftResult
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

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents")
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
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from None
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
