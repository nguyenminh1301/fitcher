"""Company documents against a running Qdrant (Phase 10 definition of done).

Set ``QDRANT_LIVE_URL`` (for example ``http://127.0.0.1:6333`` with the
Compose stack up) to run these. Each test uses its own scratch pack name, a
deterministic fake embedding model and the real EN/VI screening rules with a
classifier stub that scores everything 0, so no request is billable; the
scratch collections are deleted afterwards.
"""

from datetime import UTC, datetime
import os
from pathlib import Path
import uuid

from fakes import FakeClassifier, FakeEmbeddings
import pytest
import yaml

from app.onboarding.docs_parser import DocumentRejected
from app.onboarding.documents import DocumentService, InMemoryDocumentRegistry
from app.packs.search_indices import alias_name
from app.screening.screen import Screener
from app.search.client import QdrantSearch

LIVE_URL = os.environ.get("QDRANT_LIVE_URL", "")
ATTACKS = Path(__file__).parent / "screening" / "attacks.yaml"
pytestmark = pytest.mark.skipif(not LIVE_URL, reason="set QDRANT_LIVE_URL to a running Qdrant")


@pytest.fixture
def live(tmp_path):
    search = QdrantSearch(LIVE_URL)
    pack = f"live_docs_{uuid.uuid4().hex[:8]}"
    embeddings = FakeEmbeddings()
    screener = Screener(FakeClassifier())
    service = DocumentService(
        pack=pack, pack_roles=["analyst", "sales"], registry=InMemoryDocumentRegistry(), search=search,
        embeddings=embeddings, screener=screener, store_dir=tmp_path / "documents", compiled_dir=tmp_path / "build",
        max_bytes=100_000, clock=lambda: datetime.now(UTC),
    )
    yield service
    for name in search.list_collections():
        if name.startswith(pack):
            search.delete_collection(name)


def search_hits(service: DocumentService, text: str, roles: list[str]) -> list[dict]:
    vector = service.embeddings.embed([text])[0]
    return service.search.query(alias_name(service.pack, "kb_docs"), text, vector, roles, 10)


def test_an_uploaded_document_is_searchable_and_a_deleted_one_is_gone(live):
    record = live.upload(
        "returns.md", b"# Returns policy\n\nA refund is approved within fourteen days of the return.", ["analyst"], "lab",
    )

    hits = search_hits(live, "refund approved return", ["analyst"])
    assert [hit["source"]["document_id"] for hit in hits] == [record.id]
    assert search_hits(live, "refund approved return", ["sales"]) == []

    live.delete(record.id)
    assert search_hits(live, "refund approved return", ["analyst"]) == []


def test_a_document_carrying_an_injection_is_not_indexed(live):
    attacks = yaml.safe_load(ATTACKS.read_text(encoding="utf-8"))["items"]
    screener = live.screener
    attack = next(
        item["text"] for item in attacks
        if item["kind"] == "document" and screener.screen(item["text"], "document").verdict == "block"
    )

    benign = live.upload("returns.md", b"# Returns\n\nRefunds follow the returns policy.", ["analyst"], "lab")
    before = live.search.count(alias_name(live.pack, "kb_docs"))

    with pytest.raises(DocumentRejected, match="every chunk was blocked"):
        live.upload("note.txt", attack.encode("utf-8"), ["analyst"], "lab")

    failed = next(record for record in live.registry.list(live.pack) if record.id != benign.id)
    assert failed.status == "failed" and failed.blocked_chunks == 1
    assert live.search.count(alias_name(live.pack, "kb_docs")) == before == benign.chunk_count
