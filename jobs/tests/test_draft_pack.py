import json
from pathlib import Path
import shutil

import pytest

from jobs import draft_pack as job

API_TESTS = Path(__file__).resolve().parents[2] / "apps" / "api" / "tests"
FIXTURE_PACK = API_TESTS / "fixtures" / "packs" / "minimal"
SCHEMA_DIR = Path(__file__).resolve().parents[2] / "packs" / "_schema"


class Drafter:
    def __init__(self, llm, warehouse):
        self.calls = []

    def estimate(self, files, profile, chunks):
        return {file: 4000 for file in job.DRAFT_FILES}

    def draft(self, file, files, profile, chunks):
        self.calls.append(file)
        if file != "metrics.yaml":
            return []
        return [{"id": "widget_count", "name": "Widgets", "description": "Count.", "dataset": "widget_sales",
                 "sql_expr": "count()", "grain": "day", "unit": "count", "owner": "ops", "status": "draft",
                 "evidence": [{"kind": "profile", "ref": "widget_sales"}], "confidence": 0.5}]


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """The job opens the app state for its model clients: keep it out of the real data directory."""
    from app.state.db import reset_shared_state

    monkeypatch.setenv("FITCHER_DATA_DIR", str(tmp_path / "fitcher-data"))
    reset_shared_state()
    yield
    reset_shared_state()


@pytest.fixture
def packs_dir(tmp_path, monkeypatch):
    shutil.copytree(FIXTURE_PACK, tmp_path / "packs" / "minimal")
    shutil.copytree(SCHEMA_DIR, tmp_path / "packs" / "_schema")
    (tmp_path / "build" / "minimal").mkdir(parents=True)
    (tmp_path / "build" / "minimal" / "profile.json").write_text(json.dumps({"tables": {"widget_sales": {}}}), encoding="utf-8")
    monkeypatch.setenv("COMPILED_PACK_DIR", str(tmp_path / "build"))
    monkeypatch.setattr(job, "admin_client", lambda: object())
    monkeypatch.setattr(job, "Drafter", Drafter)
    monkeypatch.setattr(job, "read_chunks", lambda search, pack, document: [])
    return tmp_path / "packs"


def test_without_allow_billable_only_the_estimate_is_printed(packs_dir, capsys):
    before = (packs_dir / "minimal" / "metrics.yaml").read_bytes()
    assert job.main(["--pack", "minimal", "--packs-dir", str(packs_dir)]) == 2
    output = capsys.readouterr().out
    assert "metrics.yaml: about 1000 prompt tokens" in output and "--allow-billable" in output
    assert (packs_dir / "minimal" / "metrics.yaml").read_bytes() == before


def test_drafts_are_written_and_summarised(packs_dir, capsys):
    assert job.main(["--pack", "minimal", "--packs-dir", str(packs_dir), "--allow-billable"]) == 0
    assert "id: widget_count" in (packs_dir / "minimal" / "metrics.yaml").read_text(encoding="utf-8")
    assert "metrics.yaml: 1 added, 0 updated, 0 approved left unchanged" in capsys.readouterr().out
