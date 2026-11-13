"""The ``jobs/compile_pack.py`` command line, with every service replaced by a fake."""

from datetime import date
from pathlib import Path
import shutil

from conftest import FIXTURE_PACK, SCHEMA_DIR, fixture_catalog
from fakes import FakeEmbeddings, FakeSearch, FakeWarehouse
import pytest

from app.onboarding.documents import DocumentRecord, InMemoryDocumentRegistry, compile_lock_path
from jobs import compile_pack as cli


@pytest.fixture
def packs_dir(tmp_path: Path) -> Path:
    root = tmp_path / "packs"
    shutil.copytree(FIXTURE_PACK, root / "minimal")
    shutil.copytree(SCHEMA_DIR, root / "_schema")
    return root


@pytest.fixture
def services(monkeypatch, tmp_path):
    search = FakeSearch(search_results={
        "minimal_glossary_terms": [{"id": "revenue", "score": 0.9, "source": {"type": "glossary_term"}}],
        "minimal_column_values": [{"id": "widget_sales.widget_name.ab12", "score": 7.5, "source": {
            "type": "column_value", "dataset": "widget_sales", "column": "widget_name", "title": "Blue Widget",
        }}],
    })
    fake_warehouse = FakeWarehouse(
        fixture_catalog().tables, coverage={"widget_sales": (5, date(2024, 1, 1), date(2024, 12, 31))}
    )
    monkeypatch.setenv("COMPILED_PACK_DIR", str(tmp_path / "build"))
    monkeypatch.setenv("CLICKHOUSE_AGENT_PASSWORD", "lab-secret")
    monkeypatch.setattr(cli, "admin_client", lambda: object())
    monkeypatch.setattr(cli, "ClickHouseWarehouse", lambda client: fake_warehouse)
    monkeypatch.setattr(cli, "QdrantSearch", lambda url: search)
    monkeypatch.setattr(cli.clients, "index_embeddings", lambda **kwargs: (FakeEmbeddings(), "fake/embedding-model"))
    monkeypatch.setattr(cli, "ClickHouseDocumentRegistry", lambda client: registry)
    return search


registry = InMemoryDocumentRegistry()


def test_compile_prints_the_live_generation(packs_dir, services, capsys):
    code = cli.main(["--pack", "minimal", "--packs-dir", str(packs_dir)])

    out = capsys.readouterr().out
    assert code == 0
    assert "Pack minimal: 2 metrics tested (widget_revenue, refunded_value)" in out
    assert "widget_sales: 5 rows, 2024-01-01 to 2024-12-31" in out
    assert "generation v1 is live:" in out
    assert "column_values: 0 documents" in out


def test_compile_reconciles_clickhouse_access_for_every_role(packs_dir, services, capsys):
    code = cli.main(["--pack", "minimal", "--packs-dir", str(packs_dir), "--skip-index"])

    assert code == 0
    assert "access: 1 role reconciled (viewer)" in capsys.readouterr().out


def test_missing_agent_password_secret_fails_before_touching_access(packs_dir, services, capsys, monkeypatch):
    monkeypatch.delenv("CLICKHOUSE_AGENT_PASSWORD")

    code = cli.main(["--pack", "minimal", "--packs-dir", str(packs_dir), "--skip-index"])

    assert code == 1
    assert "CLICKHOUSE_AGENT_PASSWORD" in capsys.readouterr().err


def test_skip_index_touches_no_search_index(packs_dir, services, capsys):
    code = cli.main(["--pack", "minimal", "--packs-dir", str(packs_dir), "--skip-index"])

    assert code == 0
    assert "indexing skipped" in capsys.readouterr().out
    assert services.collections == {}


def test_broken_pack_exits_nonzero_with_the_reason(packs_dir, services, capsys):
    path = packs_dir / "minimal" / "metrics.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace("unit: currency", "unit: furlongs", 1), encoding="utf-8")

    code = cli.main(["--pack", "minimal", "--packs-dir", str(packs_dir)])

    assert code == 1
    assert "metrics.yaml: metrics[0].unit" in capsys.readouterr().err
    assert services.collections == {}


def test_check_search_prints_hits_per_index(packs_dir, services, capsys):
    cli.main(["--pack", "minimal", "--packs-dir", str(packs_dir)])
    capsys.readouterr()

    code = cli.main(["--pack", "minimal", "--check-search", "doanh thu"])

    out = capsys.readouterr().out
    assert code == 0
    assert "Search 'doanh thu' in minimal as viewer:" in out
    assert "glossary_terms: revenue (0.900)" in out
    assert "column_values: widget_sales.widget_name='Blue Widget' (7.500)" in out
    assert "kb_docs: no hits" in out


def test_check_search_before_any_compile_fails_clearly(services, capsys):
    code = cli.main(["--pack", "minimal", "--check-search", "doanh thu"])

    assert code == 1
    assert "compile the pack first" in capsys.readouterr().err


def test_compile_holds_the_lock_while_it_runs_and_releases_it(packs_dir, services, tmp_path, monkeypatch):
    seen = []
    original = cli.compile_pack

    def spy(*args, **kwargs):
        seen.append(compile_lock_path(tmp_path / "build", "minimal").exists())
        raise cli.CompileError("boom")

    monkeypatch.setattr(cli, "compile_pack", spy)
    assert cli.main(["--pack", "minimal", "--packs-dir", str(packs_dir)]) == 1
    assert seen == [True]
    assert not compile_lock_path(tmp_path / "build", "minimal").exists()
    assert original is not spy


def test_compile_waits_for_documents_still_processing(packs_dir, services, tmp_path, monkeypatch, capsys):
    from datetime import UTC, datetime

    now = datetime(2026, 11, 5, tzinfo=UTC)
    registry.write(DocumentRecord(
        id="d1", pack="minimal", file_name="a.md", media_type="text/markdown", size_bytes=1, sha256="x",
        uploaded_by="u", allowed_roles=["viewer"], status="processing", uploaded_at=now, updated_at=now,
    ))
    monkeypatch.setattr(cli, "UPLOAD_WAIT_SECONDS", 0)
    try:
        assert cli.main(["--pack", "minimal", "--packs-dir", str(packs_dir)]) == 1
    finally:
        registry.rows.clear()
    assert "documents are still processing: a.md" in capsys.readouterr().err
    assert not compile_lock_path(tmp_path / "build", "minimal").exists()
