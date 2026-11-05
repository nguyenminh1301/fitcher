"""Company documents of a pack: registry, stored originals and their ``kb_docs`` chunks (DECISIONS §5).

``DocumentService.upload`` checks the file before anything is stored: the
pack is not compiling, the size cap, ``allowed_roles`` (a non-empty subset of
the pack's roles), the media type from the content, and a SHA-256 not already
registered for the pack. It then records a ``processing`` row, stores the
original, parses, chunks and screens every chunk (DECISIONS §9), embeds the
kept chunks through the ``embed`` tier and writes them to the pack's live
``kb_docs`` alias before marking the row ``indexed``. A failure after the row
exists marks it ``failed`` with the reason and leaves no chunk and no stored
file; so does a document whose every chunk screening blocked.

Delete removes the chunks and the file and marks the row deleted. Both are
refused while ``compile_pack`` holds the pack's compile lock, so a compile
never drops or restores a document. The api runs one worker; a lock in the
service serializes its changes.
"""

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
import hashlib
import os
from pathlib import Path
import threading
from typing import Literal, Protocol
import uuid

import clickhouse_connect
from pydantic import BaseModel, ConfigDict

from app.llm.embeddings import EmbeddingClient
from app.observability.tracing import trusted_pack_calls
from app.onboarding.chunker import DEFAULT_MAX_CHARS, Chunk, chunk_sections
from app.onboarding.docs_parser import DocumentRejected, detect_media_type, parse_document
from app.packs.search_indices import alias_name, physical_name, points
from app.search.client import document_filter

KB_DOCS = "kb_docs"
CHUNK_TYPE = "doc_chunk"
STALE_LOCK = timedelta(hours=6)
ERROR_LIMIT = 500
TABLE = "data_meta.documents"
COLUMNS = (
    "id", "pack", "file_name", "media_type", "size_bytes", "sha256", "uploaded_by", "allowed_roles", "status",
    "error", "chunk_count", "blocked_chunks", "uploaded_at", "deleted_at", "updated_at",
)


class PackCompiling(Exception):
    """The pack is compiling; documents cannot change until it finishes."""


class DuplicateDocument(Exception):
    """A document with the same content is already registered for the pack."""


class DocumentNotFound(Exception):
    """No live document has this id in the pack."""


class DocumentRecord(BaseModel):
    """One row of ``data_meta.documents``."""

    model_config = ConfigDict(extra="forbid")

    id: str
    pack: str
    file_name: str
    media_type: str
    size_bytes: int
    sha256: str
    uploaded_by: str
    allowed_roles: list[str]
    status: Literal["processing", "indexed", "failed"]
    error: str = ""
    chunk_count: int = 0
    blocked_chunks: int = 0
    uploaded_at: datetime
    deleted_at: datetime | None = None
    updated_at: datetime


class DocumentRegistry(Protocol):
    def get(self, pack: str, document_id: str) -> DocumentRecord | None:
        """The latest row of a document, deleted or not."""

    def list(self, pack: str) -> list[DocumentRecord]:
        """Documents that are not deleted, newest upload first."""

    def write(self, record: DocumentRecord) -> None:
        """Store a new version of the row."""


def find_duplicate(registry: DocumentRegistry, pack: str, sha256: str) -> DocumentRecord | None:
    """A live, not failed document of the pack with this content."""
    return next((record for record in registry.list(pack) if record.sha256 == sha256 and record.status != "failed"), None)


def processing(registry: DocumentRegistry, pack: str) -> list[DocumentRecord]:
    return [record for record in registry.list(pack) if record.status == "processing"]


class InMemoryDocumentRegistry:
    """The registry in a dict, for tests and for jobs that run without ClickHouse."""

    def __init__(self):
        self.rows: dict[tuple[str, str], DocumentRecord] = {}

    def get(self, pack: str, document_id: str) -> DocumentRecord | None:
        return self.rows.get((pack, document_id))

    def list(self, pack: str) -> list[DocumentRecord]:
        live = [record for (owner, _), record in self.rows.items() if owner == pack and record.deleted_at is None]
        return sorted(live, key=lambda record: record.uploaded_at, reverse=True)

    def write(self, record: DocumentRecord) -> None:
        self.rows[(record.pack, record.id)] = record.model_copy(deep=True)


class ClickHouseDocumentRegistry:
    """``data_meta.documents`` through a clickhouse-connect client; the latest ``updated_at`` of an id wins."""

    def __init__(self, client):
        self._client = client

    def _select(self, where: str, parameters: dict) -> list[DocumentRecord]:
        sql = f"SELECT {', '.join(COLUMNS)} FROM {TABLE} FINAL WHERE {where} ORDER BY uploaded_at DESC"
        rows = self._client.query(sql, parameters=parameters).result_rows
        return [DocumentRecord(**_aware(dict(zip(COLUMNS, row, strict=True)))) for row in rows]

    def get(self, pack: str, document_id: str) -> DocumentRecord | None:
        found = self._select("pack = {pack:String} AND id = {id:String}", {"pack": pack, "id": document_id})
        return found[0] if found else None

    def list(self, pack: str) -> list[DocumentRecord]:
        return self._select("pack = {pack:String} AND deleted_at IS NULL", {"pack": pack})

    def write(self, record: DocumentRecord) -> None:
        row = record.model_dump()
        self._client.insert(TABLE, [[row[column] for column in COLUMNS]], column_names=list(COLUMNS))


def pack_review_client(env: Mapping[str, str] | None = None):
    """A ClickHouse client as ``pack_review``, the only api user that writes the document registry."""
    env = os.environ if env is None else env
    password = env.get("CLICKHOUSE_PACK_REVIEW_PASSWORD", "")
    if not password:
        raise RuntimeError("CLICKHOUSE_PACK_REVIEW_PASSWORD must be set")
    return clickhouse_connect.get_client(
        host=env.get("CLICKHOUSE_HOST", "clickhouse"), port=int(env.get("CLICKHOUSE_HTTP_PORT", "8123")),
        username="pack_review", password=password,
    )


def _aware(row: dict) -> dict:
    for key in ("uploaded_at", "deleted_at", "updated_at"):
        if isinstance(row[key], datetime) and row[key].tzinfo is None:
            row[key] = row[key].replace(tzinfo=UTC)
    return row


def compile_lock_path(compiled_dir: Path, pack: str) -> Path:
    return compiled_dir / pack / "compiling"


def is_compiling(compiled_dir: Path, pack: str, now: datetime) -> bool:
    """Whether ``compile_pack`` holds the pack's lock; a lock older than six hours is a crashed run and ignored."""
    path = compile_lock_path(compiled_dir, pack)
    try:
        started = datetime.fromisoformat(path.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        return path.exists()
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    return now - started < STALE_LOCK


def _first_line(error: BaseException) -> str:
    return (" ".join(str(error).split()) or type(error).__name__)[:ERROR_LIMIT]


def live_chunks(search, pack: str, document_id: str | None = None) -> list[dict]:
    """Payloads of the live ``kb_docs`` chunks, of one document or of all, in document and chunk order."""
    flt = document_filter(document_id) if document_id else None
    payloads = [point["payload"] for point in search.scroll(alias_name(pack, KB_DOCS), flt)]
    return sorted(payloads, key=lambda payload: (payload["document_id"], int(payload["id"].rsplit("#", 1)[1])))


def chunk_payloads(record: DocumentRecord, chunks: Sequence[Chunk]) -> list[dict]:
    """The ``kb_docs`` documents of a record's chunks; ``embedding_text`` is embedded and not stored."""
    documents = []
    for number, chunk in enumerate(chunks):
        title = " › ".join([record.file_name, *chunk.heading_path])
        documents.append({
            "id": f"{record.id}#{number}", "type": CHUNK_TYPE, "pack": record.pack, "document_id": record.id,
            "source": record.file_name, "heading_path": list(chunk.heading_path), "allowed_roles": list(record.allowed_roles),
            "title": title, "text": chunk.text, "embedding_text": f"{title}\n{chunk.text}",
        })
    return documents


def screen_chunks(screener, chunks: Sequence[Chunk]) -> tuple[list[Chunk], int]:
    """Chunks screening lets through, and how many it blocked (``block`` or, without the classifier, ``unavailable``)."""
    verdicts = screener.screen_many([chunk.text for chunk in chunks], "document")
    kept = [chunk for chunk, verdict in zip(chunks, verdicts, strict=True) if verdict.verdict not in ("block", "unavailable")]
    return kept, len(chunks) - len(kept)


class DocumentService:
    def __init__(
        self,
        *,
        pack: str,
        pack_roles: Sequence[str],
        registry: DocumentRegistry,
        search,
        embeddings: EmbeddingClient,
        screener,
        store_dir: Path,
        compiled_dir: Path,
        max_bytes: int,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        max_chars: int = DEFAULT_MAX_CHARS,
    ):
        self.pack = pack
        self.pack_roles = list(pack_roles)
        self.registry = registry
        self.search = search
        self.embeddings = embeddings
        self.screener = screener
        self.store_dir = store_dir
        self.compiled_dir = compiled_dir
        self.max_bytes = max_bytes
        self.clock = clock
        self.max_chars = max_chars
        self._changes = threading.Lock()

    @property
    def alias(self) -> str:
        return alias_name(self.pack, KB_DOCS)

    def compiling(self) -> bool:
        return is_compiling(self.compiled_dir, self.pack, self.clock())

    def stored_path(self, document_id: str) -> Path:
        return self.store_dir / self.pack / document_id

    def _check_roles(self, roles: Sequence[str]) -> list[str]:
        if not roles:
            raise DocumentRejected("choose at least one role that may read the document")
        unknown = sorted(set(roles) - set(self.pack_roles))
        if unknown:
            raise DocumentRejected(f"not roles of this pack: {', '.join(unknown)}")
        return [role for role in self.pack_roles if role in set(roles)]

    def _save(self, record: DocumentRecord, **changes) -> DocumentRecord:
        # Each version is at least 1 ms after the previous one, so the registry keeps the latest.
        updated_at = max(self.clock(), record.updated_at + timedelta(milliseconds=1))
        record = record.model_copy(update={**changes, "updated_at": updated_at})
        self.registry.write(record)
        return record

    def _live(self, document_id: str) -> DocumentRecord:
        record = self.registry.get(self.pack, document_id)
        if record is None or record.deleted_at is not None:
            raise DocumentNotFound(document_id)
        return record

    def _guard(self) -> None:
        if self.compiling():
            raise PackCompiling(f"pack {self.pack} is compiling; try again when it finishes")

    def upload(self, file_name: str, data: bytes, allowed_roles: Sequence[str], uploaded_by: str) -> DocumentRecord:
        with self._changes:
            self._guard()
            if len(data) > self.max_bytes:
                raise DocumentRejected(f"the file is larger than {self.max_bytes} bytes", 413)
            roles = self._check_roles(allowed_roles)
            media_type = detect_media_type(data, file_name)
            sha256 = hashlib.sha256(data).hexdigest()
            if duplicate := find_duplicate(self.registry, self.pack, sha256):
                raise DuplicateDocument(f"the same file is already registered as {duplicate.file_name}")
            now = self.clock()
            record = DocumentRecord(
                id=uuid.uuid4().hex, pack=self.pack, file_name=file_name, media_type=media_type, size_bytes=len(data),
                sha256=sha256, uploaded_by=uploaded_by, allowed_roles=roles, status="processing",
                uploaded_at=now, updated_at=now,
            )
            self.registry.write(record)
            try:
                return self._index(record, data)
            except Exception as error:
                self._discard(record)
                self._save(self.registry.get(self.pack, record.id) or record, status="failed", error=_first_line(error))
                raise

    def _index(self, record: DocumentRecord, data: bytes) -> DocumentRecord:
        path = self.stored_path(record.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        chunks = chunk_sections(parse_document(data, record.media_type), record.media_type, self.max_chars)
        kept, blocked = screen_chunks(self.screener, chunks)
        if not kept:
            self.registry.write(record.model_copy(update={"blocked_chunks": blocked}))
            raise DocumentRejected("every chunk was blocked by input screening")
        documents = chunk_payloads(record, kept)
        # The chunks were screened above, so the gateway takes them as checked content (DECISIONS §9).
        with trusted_pack_calls():
            vectors = self.embeddings.embed([document["embedding_text"] for document in documents])
        self._ensure_alias()
        self.search.upsert(self.alias, points(self.alias, documents, vectors))
        return self._save(record, status="indexed", chunk_count=len(kept), blocked_chunks=blocked)

    def _ensure_alias(self) -> None:
        """Give a pack that was never compiled a ``kb_docs`` generation 0; its first compile replaces it."""
        if self.alias in self.search.alias_targets():
            return
        name = physical_name(self.pack, KB_DOCS, 0)
        if name not in self.search.list_collections():
            self.search.create_collection(name, self.embeddings.dimensions)
        self.search.update_aliases([{"create_alias": {"collection_name": name, "alias_name": self.alias}}])

    def _discard(self, record: DocumentRecord) -> None:
        try:
            self.search.delete_points(self.alias, document_filter(record.id))
        except Exception:  # noqa: BLE001, S110 - cleanup must not hide the original failure
            pass
        self.stored_path(record.id).unlink(missing_ok=True)

    def delete(self, document_id: str) -> None:
        with self._changes:
            self._guard()
            record = self._live(document_id)
            self.search.delete_points(self.alias, document_filter(document_id))
            self.stored_path(document_id).unlink(missing_ok=True)
            self._save(record, deleted_at=self.clock())

    def set_roles(self, document_id: str, allowed_roles: Sequence[str]) -> DocumentRecord:
        with self._changes:
            self._guard()
            record = self._live(document_id)
            roles = self._check_roles(allowed_roles)
            if record.status == "indexed":
                self.search.set_payload(self.alias, {"allowed_roles": roles}, document_filter(document_id))
            return self._save(record, allowed_roles=roles)

    def chunks(self, document_id: str | None = None) -> list[dict]:
        """Payloads of the live ``kb_docs`` chunks, of one document or of all, in document and chunk order."""
        return live_chunks(self.search, self.pack, document_id)

    def list(self) -> list[DocumentRecord]:
        return self.registry.list(self.pack)
