"""Company documents as the console's Documents page shows them (DECISIONS §5 and §15)."""

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.contracts.query_spec import ContractModel


class DocumentView(ContractModel):
    id: str
    name: str
    size: int
    media_type: str
    status: Literal["processing", "indexed", "failed"]
    # Why the document failed; empty otherwise.
    error: str = ""
    # Pack roles that may read the document's chunks.
    roles: list[str]
    chunk_count: int
    # Chunks input screening kept out of kb_docs.
    blocked_chunks: int
    uploaded_by: str
    uploaded_at: datetime


class DocumentList(ContractModel):
    # While the pack compiles, uploads and deletes are refused.
    compiling: bool
    documents: list[DocumentView]


class DraftResult(ContractModel):
    """Review ids (``<file stem>.<item id>``) of the items a draft added, refreshed or left because they are approved."""

    added: list[str]
    updated: list[str]
    skipped_approved: list[str]


class DocumentRolesChange(ContractModel):
    allowed_roles: list[str] = Field(min_length=1)


class DocumentSettings(ContractModel):
    enabled: bool
    # Documents of the active pack that are kept, indexed or not; 0 without an active pack.
    documents: int


class DocumentSettingsChange(ContractModel):
    enabled: bool
    # Turning documents off while documents exist needs this, after the user saw that they are kept.
    confirm: bool = False
