import json
from pathlib import Path

import pytest

from jobs import profile as job


@pytest.fixture
def packs_dir(tmp_path: Path) -> Path:
    pack = tmp_path / "packs" / "lab"
    pack.mkdir(parents=True)
    (pack / "datasets.yaml").write_text("datasets:\n  - id: orders\n  - id: lines\n", encoding="utf-8")
    (tmp_path / "packs" / "empty").mkdir()
    return tmp_path / "packs"


@pytest.fixture
def profiled(monkeypatch, tmp_path):
    calls = []

    def fake_profile(warehouse, tables, **kwargs):
        calls.append(list(tables))
        return {"profiled_at": "now", "tables": {table: {"rows": 7, "columns": {}, "sample_rows": []} for table in tables},
                "join_candidates": []}

    monkeypatch.setenv("COMPILED_PACK_DIR", str(tmp_path / "build"))
    monkeypatch.setattr(job, "admin_client", lambda: object())
    monkeypatch.setattr(job, "profile_marts", fake_profile)
    return calls


def test_profile_defaults_to_the_packs_datasets_and_writes_profile_json(packs_dir, profiled, tmp_path, capsys):
    assert job.main(["--pack", "lab", "--packs-dir", str(packs_dir)]) == 0
    assert profiled == [["orders", "lines"]]
    written = json.loads((tmp_path / "build" / "lab" / "profile.json").read_text(encoding="utf-8"))
    assert set(written["tables"]) == {"orders", "lines"}
    assert "orders: 7 rows" in capsys.readouterr().out


def test_tables_option_overrides_the_datasets(packs_dir, profiled):
    assert job.main(["--pack", "lab", "--packs-dir", str(packs_dir), "--tables", "a,b"]) == 0
    assert profiled == [["a", "b"]]


def test_a_pack_without_datasets_needs_tables(packs_dir, profiled, capsys):
    assert job.main(["--pack", "empty", "--packs-dir", str(packs_dir)]) == 2
    assert "--tables" in capsys.readouterr().err
    assert profiled == []
