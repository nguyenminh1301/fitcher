from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.onboarding.documents import DocumentService, InMemoryDocumentRegistry
from jobs import ingest_docs as job

NOW = datetime(2026, 11, 5, tzinfo=UTC)


class AllowAll:
    classifier = object()

    def screen_many(self, texts, source):
        return [SimpleNamespace(verdict="allow") for _ in texts]


class Embeddings:
    dimensions = 2

    def embed(self, texts):
        return [[1.0, 0.0] for _ in texts]


class Search:
    def __init__(self):
        self.points = []
        self.aliases = {}

    def alias_targets(self):
        return self.aliases

    def list_collections(self):
        return []

    def create_collection(self, name, dimensions):
        pass

    def update_aliases(self, actions):
        self.aliases.update({a["create_alias"]["alias_name"]: a["create_alias"]["collection_name"] for a in actions})

    def upsert(self, name, points):
        self.points.extend(points)

    def delete_points(self, name, flt):
        pass


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    (tmp_path / "notes.md").write_bytes(b"# Notes\n\nReturns are counted on the return date.")
    (tmp_path / "empty.txt").write_bytes(b"")
    (tmp_path / "manifest.yaml").write_text(
        "default_allowed_roles: [analyst]\n"
        "documents:\n  - file: notes.md\n  - file: empty.txt\n    allowed_roles: [analyst, sales]\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def service(tmp_path):
    return DocumentService(
        pack="lab", pack_roles=["analyst", "sales"], registry=InMemoryDocumentRegistry(), search=Search(),
        embeddings=Embeddings(), screener=AllowAll(), store_dir=tmp_path / "store", compiled_dir=tmp_path / "build",
        max_bytes=1000, clock=lambda: NOW,
    )


def test_manifest_applies_default_roles(folder):
    assert [(file.name, roles) for file, roles in job.read_manifest(folder)] == [
        ("notes.md", ["analyst"]), ("empty.txt", ["analyst", "sales"]),
    ]


def test_ingest_indexes_documents_skips_duplicates_and_counts_failures(folder, service, capsys):
    entries = job.read_manifest(folder)
    assert job.ingest(service, entries, "jobs.ingest_docs") == 1
    assert job.ingest(service, entries[:1], "jobs.ingest_docs") == 0
    output = capsys.readouterr().out
    assert "indexed notes.md: 1 chunks" in output
    assert "failed empty.txt: the file is empty" in output
    assert "skipped notes.md" in output


@pytest.mark.parametrize(("manifest", "message"), [
    (None, "does not exist"),
    ("documents: []\n", "lists no documents"),
    ("documents:\n  - file: missing.pdf\n", "missing.pdf does not exist"),
])
def test_unusable_manifests_exit_2(tmp_path, capsys, manifest, message):
    if manifest is not None:
        (tmp_path / "manifest.yaml").write_text(manifest, encoding="utf-8")
    assert job.main(["--pack", "lab", "--folder", str(tmp_path)]) == 2
    assert message in capsys.readouterr().err
