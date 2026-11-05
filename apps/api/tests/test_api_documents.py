"""POST/GET/PATCH/DELETE /documents over a real DocumentService with in-memory stores."""

from datetime import UTC, datetime

from fastapi.testclient import TestClient
import pytest

from agent_fixtures import compiled_fixture
from auth_fixtures import token, verifier
from document_fixtures import MARKDOWN
from fakes import FakeEmbeddings, FakeSearch
from test_documents_service import WordScreener

from app.api import runtime
from app.main import app
from app.onboarding.documents import DocumentService, InMemoryDocumentRegistry, compile_lock_path

NOW = datetime(2026, 11, 5, 8, 0, tzinfo=UTC)
REVIEWER = {"Authorization": f"Bearer {token(realm_access={'roles': ['pack_reviewer']})}"}
VIEWER = {"Authorization": f"Bearer {token()}"}


@pytest.fixture
def service(tmp_path):
    search = FakeSearch()
    search.create_collection("minimal_kb_docs_v1", 4)
    search.aliases["minimal_kb_docs"] = "minimal_kb_docs_v1"
    return DocumentService(
        pack="minimal", pack_roles=["viewer"], registry=InMemoryDocumentRegistry(), search=search,
        embeddings=FakeEmbeddings(), screener=WordScreener(), store_dir=tmp_path / "documents",
        compiled_dir=tmp_path / "compiled", max_bytes=10_000, clock=lambda: NOW,
    )


@pytest.fixture
def client(service):
    app.dependency_overrides[runtime.get_verifier] = lambda: verifier()
    app.dependency_overrides[runtime.get_compiled] = lambda: compiled_fixture()
    app.dependency_overrides[runtime.get_document_service] = lambda: service
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def upload(client, data=MARKDOWN, name="glossary.md", roles=("viewer",), headers=REVIEWER):
    return client.post("/documents", headers=headers, files={"file": (name, data, "application/octet-stream")},
                       data={"allowed_roles": list(roles)})


def test_upload_indexes_the_document_and_lists_it(client):
    response = upload(client)

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "glossary.md" and body["status"] == "indexed" and body["roles"] == ["viewer"]
    assert body["chunk_count"] == 3 and body["blocked_chunks"] == 0 and body["uploaded_by"] == "lab.viewer"
    listed = client.get("/documents", headers=REVIEWER).json()
    assert listed["compiling"] is False
    assert [item["id"] for item in listed["documents"]] == [body["id"]]


@pytest.mark.parametrize(("kwargs", "status", "detail"), [
    ({"data": b"x" * 10_001}, 413, "larger than"),
    ({"roles": ()}, 422, "at least one"),
    ({"roles": ("stranger",)}, 422, "stranger"),
    ({"data": b"PK\x03\x04junk", "name": "a.pdf"}, 415, "not a supported type"),
    ({"data": b"%PDF-1.4\n"}, 422, "PDF"),
])
def test_upload_rejections(client, kwargs, status, detail):
    response = upload(client, **kwargs)
    assert response.status_code == status
    assert detail in response.json()["detail"]


def test_a_duplicate_upload_is_a_conflict(client):
    upload(client)
    response = upload(client, name="copy.md")
    assert response.status_code == 409 and "glossary.md" in response.json()["detail"]


def test_upload_and_delete_wait_while_the_pack_compiles(client, service, tmp_path):
    document = upload(client).json()
    lock = compile_lock_path(tmp_path / "compiled", "minimal")
    lock.parent.mkdir(parents=True)
    lock.write_text(NOW.isoformat(), encoding="utf-8")

    assert upload(client, data=b"Other.", name="other.txt").status_code == 409
    assert client.delete(f"/documents/{document['id']}", headers=REVIEWER).status_code == 409
    assert client.get("/documents", headers=REVIEWER).json()["compiling"] is True


def test_delete_removes_the_document(client):
    document = upload(client).json()
    assert client.delete(f"/documents/{document['id']}", headers=REVIEWER).status_code == 204
    assert client.get("/documents", headers=REVIEWER).json()["documents"] == []
    assert client.delete(f"/documents/{document['id']}", headers=REVIEWER).status_code == 404


def test_patch_changes_the_roles(client):
    document = upload(client).json()
    response = client.patch(f"/documents/{document['id']}", headers=REVIEWER, json={"allowed_roles": ["viewer"]})
    assert response.status_code == 200 and response.json()["roles"] == ["viewer"]
    bad = client.patch(f"/documents/{document['id']}", headers=REVIEWER, json={"allowed_roles": ["stranger"]})
    assert bad.status_code == 422


@pytest.mark.parametrize(("method", "path"), [
    ("get", "/documents"), ("delete", "/documents/abc"), ("patch", "/documents/abc"),
])
def test_only_a_pack_reviewer_reaches_documents(client, method, path):
    response = client.request(method.upper(), path, headers=VIEWER, json={"allowed_roles": ["viewer"]})
    assert response.status_code == 403
    assert upload(client, headers=VIEWER).status_code == 403


class StubDrafter:
    def __init__(self):
        self.chunks = []

    def draft(self, file, files, profile, chunks):
        self.chunks.append([chunk["document_id"] for chunk in chunks])
        if file != "glossary.yaml":
            return []
        return [{"id": "revenue", "term": "x", "definition": "x", "aliases": {"vi": ["x"], "en": ["x"]},
                 "targets": [{"kind": "metric", "metric": "widget_revenue"}], "evidence": [{"kind": "doc", "ref": "a"}],
                 "confidence": 0.5, "status": "draft"},
                {"id": "widget_term", "term": "widget", "definition": "A thing sold.", "aliases": {"vi": ["hàng"], "en": ["widget"]},
                 "targets": [{"kind": "metric", "metric": "widget_revenue"}], "evidence": [{"kind": "doc", "ref": "a"}],
                 "confidence": 0.5, "status": "draft"}]


@pytest.fixture
def drafting(client, tmp_path):
    import shutil

    from conftest import FIXTURE_PACK, SCHEMA_DIR

    pack_dir = tmp_path / "packs" / "minimal"
    shutil.copytree(FIXTURE_PACK, pack_dir)
    shutil.copytree(SCHEMA_DIR, tmp_path / "packs" / "_schema")
    drafter = StubDrafter()
    app.dependency_overrides[runtime.get_drafter] = lambda: drafter
    app.dependency_overrides[runtime.get_pack_dir] = lambda: pack_dir
    return drafter, pack_dir


def test_draft_from_one_document_writes_drafts_and_reports_review_ids(client, drafting):
    drafter, pack_dir = drafting
    first = upload(client).json()
    upload(client, data=b"Another document.", name="other.txt")

    response = client.post(f"/documents/{first['id']}/draft", headers=REVIEWER)

    assert response.status_code == 200
    assert response.json() == {"added": ["glossary.widget_term"], "updated": [], "skipped_approved": ["glossary.revenue"]}
    assert all(ids == [first["id"]] * 3 for ids in drafter.chunks)
    assert "id: widget_term" in (pack_dir / "glossary.yaml").read_text(encoding="utf-8")


def test_draft_needs_an_indexed_document(client, drafting):
    assert client.post("/documents/nope/draft", headers=REVIEWER).status_code == 404
    assert client.post("/documents/nope/draft", headers=VIEWER).status_code == 403
