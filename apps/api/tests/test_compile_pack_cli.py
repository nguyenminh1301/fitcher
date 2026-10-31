"""The ``jobs/compile_pack.py`` command line, with every service replaced by a fake."""

from datetime import date
from pathlib import Path
import shutil

from conftest import FIXTURE_PACK, SCHEMA_DIR, fixture_catalog
from fakes import FakeEmbeddings, FakeSearch, FakeWarehouse
import pytest

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
    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-test")
    monkeypatch.setattr(cli, "admin_client", lambda: object())
    monkeypatch.setattr(cli, "ClickHouseWarehouse", lambda client: fake_warehouse)
    monkeypatch.setattr(cli, "OpenSearch", lambda url: search)
    monkeypatch.setattr(cli, "LiteLLMEmbeddings", lambda *args: FakeEmbeddings())
    return search


def test_compile_prints_the_live_generation(packs_dir, services, capsys):
    code = cli.main(["--pack", "minimal", "--packs-dir", str(packs_dir)])

    out = capsys.readouterr().out
    assert code == 0
    assert "Pack minimal: 2 metrics tested (widget_revenue, refunded_value)" in out
    assert "widget_sales: 5 rows, 2024-01-01 to 2024-12-31" in out
    assert "generation v1 is live:" in out
    assert "column_values: 0 documents" in out


def test_skip_index_touches_no_search_index(packs_dir, services, capsys):
    code = cli.main(["--pack", "minimal", "--packs-dir", str(packs_dir), "--skip-index"])

    assert code == 0
    assert "indexing skipped" in capsys.readouterr().out
    assert services.indices == {}


def test_broken_pack_exits_nonzero_with_the_reason(packs_dir, services, capsys):
    path = packs_dir / "minimal" / "metrics.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace("unit: currency", "unit: furlongs", 1), encoding="utf-8")

    code = cli.main(["--pack", "minimal", "--packs-dir", str(packs_dir)])

    assert code == 1
    assert "metrics.yaml: metrics[0].unit" in capsys.readouterr().err
    assert services.indices == {}


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
