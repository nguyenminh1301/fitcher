"""The instant pack pipeline: marts, profile, files, draft, approve, compile and activate as one job (DECISIONS §11)."""

from pathlib import Path
import shutil

from conftest import SCHEMA_DIR
import pytest

from app.onboarding.instant import STEPS, InstantPipeline, InstantRefused
from app.sources.inspect import CatalogColumn, ForeignKey
from app.sources.store import StoredTable


def _table(name, columns, foreign_keys=(), primary_key=()):
    return StoredTable(
        source_id="shop", name=name, kind="table", selected=True, mode="copy", proposed_mode="copy", reason="",
        row_estimate=10, size_bytes=100, columns=tuple(CatalogColumn(c, "text", True, i) for i, c in enumerate(columns, 1)),
        primary_key=primary_key, foreign_keys=foreign_keys, unusual_columns=(), interval_seconds=86400,
        cursor_column=None, cursor_value=None, next_run_at=None, last_synced_at=None, last_rows=None,
    )


TABLES = [
    _table("widgets", ["widget_id", "widget_name"], primary_key=("widget_id",)),
    _table("sales", ["sale_id", "sold_on", "widget_id", "sale_amount"], primary_key=("sale_id",),
           foreign_keys=(ForeignKey(("widget_id",), "widgets", ("widget_id",)),)),
]
DESCRIBE = {
    "`raw`.`shop__widgets`": [("widget_id", "Int64"), ("widget_name", "String")],
    "`raw`.`shop__sales`": [("sale_id", "Int64"), ("sold_on", "String"), ("widget_id", "Int64"), ("sale_amount", "Float64")],
}


class _Rows:
    def __init__(self, rows):
        self.result_rows = rows


class FakeClickHouse:
    """Answers DESCRIBE, the text sample, the profile queries and lists the source's views."""

    def __init__(self):
        self.commands: list[str] = []
        self.views: set[str] = set()

    def query(self, sql, settings=None, parameters=None):
        if sql.startswith("DESCRIBE TABLE "):
            return _Rows([(name, kind) for name, kind in DESCRIBE[sql.removeprefix("DESCRIBE TABLE ")]])
        if sql.startswith("SELECT countIf"):
            return _Rows([(5, 5, 0, 0, 5, 0, 0, 0)][:1] if "sold_on" in sql else [(5, 0, 0, 0)])
        if sql.startswith("SELECT name FROM system.tables"):
            return _Rows([(name,) for name in sorted(self.views)])
        if "FROM system.columns" in sql:
            rows = []
            for view in self.views:
                for name, kind in self._columns(view):
                    rows.append((view, name, kind))
            return _Rows(rows)
        if sql.startswith("SELECT count()"):
            return _Rows([(3,)])
        if "uniqExact" in sql:
            return _Rows([(3,)])
        if "min(" in sql:
            return _Rows([("2025-01-01", "2025-03-01")])
        return _Rows([])

    @staticmethod
    def _columns(view):
        base = {"shop__widgets": [("widget_id", "Int64"), ("widget_name", "String")],
                "shop__sales": [("sale_id", "Int64"), ("sold_on", "Nullable(Date)"), ("widget_id", "Int64"), ("sale_amount", "Float64")]}
        if view == "shop__sales__wide":
            return base["shop__sales"] + [("widgets_widget_name", "String")]
        return base[view]

    def command(self, sql, settings=None):
        self.commands.append(sql)
        if sql.startswith("CREATE OR REPLACE VIEW"):
            self.views.add(sql.split("`marts`.`")[1].split("`")[0])
        elif sql.startswith("DROP VIEW"):
            self.views.discard(sql.rsplit("`", 2)[1])


class FakeDrafter:
    def __init__(self, fail: bool = False):
        self.fail, self.calls = fail, []

    def draft(self, file, files, profile, chunks):
        self.calls.append(file)
        if self.fail:
            raise RuntimeError("the model provider refused the request")
        if file == "examples.yaml":
            return [{"id": f"q{n}", "question": f"Question {n}?", "language": "en", "sql": "SELECT 1",
                     "datasets": ["shop__sales__wide"], "metrics": [], "evidence": [{"kind": "profile", "ref": "shop__sales"}],
                     "confidence": 0.5} for n in range(1, 5)]
        return []

    def estimate(self, files, profile, chunks):
        return {"datasets.yaml": 400, "glossary.yaml": 400, "metrics.yaml": 400, "examples.yaml": 400}


class Store:
    def tables(self, source_id):
        return TABLES

    def get(self, source_id):
        return type("Source", (), {"id": source_id, "kind": "postgres"})()


@pytest.fixture
def packs_dir(tmp_path: Path) -> Path:
    shutil.copytree(SCHEMA_DIR, tmp_path / "packs" / "_schema")
    return tmp_path / "packs"


def _pipeline(packs_dir, drafter=None, compile_fails=False, model_missing=None, client=None):
    compiled, activated = [], []

    def compile_pack(pack_dir: Path):
        compiled.append(pack_dir.name)
        if compile_fails:
            raise RuntimeError("index generation failed")
        return {"generation": 2}

    pipeline = InstantPipeline(
        store=Store(), client=client or FakeClickHouse(), packs_dir=packs_dir, schema_dir=packs_dir / "_schema",
        drafter=lambda: drafter or FakeDrafter(), compile_pack=compile_pack, activate=activated.append,
        model_missing=lambda: model_missing,
    )
    return pipeline, compiled, activated


def test_the_draft_is_billable_and_needs_an_explicit_confirmation(packs_dir):
    pipeline, _, _ = _pipeline(packs_dir)

    with pytest.raises(InstantRefused, match="confirm"):
        pipeline.start("shop", ["widgets", "sales"], confirm_billable=False, started_by="owner")


def test_the_estimate_counts_prompt_tokens_before_anything_runs(packs_dir):
    pipeline, compiled, _ = _pipeline(packs_dir)

    estimate = pipeline.estimate("shop", ["widgets", "sales"])

    assert estimate == {"prompt_tokens": 400, "datasets": 3, "model_missing": None}
    assert compiled == []


def test_a_job_runs_every_step_and_activates_the_compiled_pack(packs_dir):
    client = FakeClickHouse()
    pipeline, compiled, activated = _pipeline(packs_dir, client=client)

    job = pipeline.run(pipeline.new_job("shop", ["widgets", "sales"], started_by="owner"))

    assert job.status == "succeeded"
    assert [step["id"] for step in job.steps] == list(STEPS) and {step["state"] for step in job.steps} == {"done"}
    assert compiled == ["shop"] and activated == ["shop"]
    assert job.result["pack"] == "shop"
    assert job.result["suggested_questions"] == ["Question 1?", "Question 2?", "Question 3?"]
    assert client.views == {"shop__widgets", "shop__sales", "shop__sales__wide"}
    assert (packs_dir / "shop" / "datasets.yaml").is_file() and not (packs_dir / "shop.building").exists()


def test_a_failed_step_leaves_the_previous_pack_live_and_names_the_step(packs_dir):
    (packs_dir / "shop").mkdir()
    (packs_dir / "shop" / "datasets.yaml").write_text("previous\n", encoding="utf-8")
    pipeline, _, activated = _pipeline(packs_dir, compile_fails=True)

    job = pipeline.run(pipeline.new_job("shop", ["widgets", "sales"], started_by="owner"))

    assert job.status == "failed" and job.failed_step == "compile"
    assert "index generation failed" in job.error
    assert (packs_dir / "shop" / "datasets.yaml").read_text(encoding="utf-8") == "previous\n"
    assert activated == []


def test_without_a_model_the_job_stops_before_the_draft_and_says_what_is_missing(packs_dir):
    drafter = FakeDrafter()
    pipeline, compiled, _ = _pipeline(packs_dir, drafter=drafter, model_missing="no model is mapped to the sql-gen tier")

    job = pipeline.run(pipeline.new_job("shop", ["widgets", "sales"], started_by="owner"))

    assert job.status == "failed" and job.failed_step == "draft"
    assert job.error == "no model is mapped to the sql-gen tier"
    assert drafter.calls == [] and compiled == []


def test_a_drafter_failure_is_reported_on_its_step(packs_dir):
    pipeline, _, _ = _pipeline(packs_dir, drafter=FakeDrafter(fail=True))

    job = pipeline.run(pipeline.new_job("shop", ["widgets", "sales"], started_by="owner"))

    assert (job.status, job.failed_step) == ("failed", "draft")
    assert [step["state"] for step in job.steps] == ["done", "done", "done", "failed", "pending", "pending", "pending"]


def test_tables_that_the_source_does_not_list_are_refused(packs_dir):
    pipeline, _, _ = _pipeline(packs_dir)

    with pytest.raises(InstantRefused, match="unknown table"):
        pipeline.start("shop", ["widgets", "nope"], confirm_billable=True, started_by="owner")


def test_a_built_pack_keeps_the_columns_its_tables_had_so_drift_can_be_shown(packs_dir):
    from app.onboarding.drift import read_snapshot
    pipeline, _, _ = _pipeline(packs_dir)

    pipeline.run(pipeline.new_job("shop", ["widgets", "sales"], started_by="owner"))

    snapshot = read_snapshot(packs_dir / "shop")
    assert snapshot["source"] == "shop" and snapshot["tables"]["widgets"] == [["widget_id", "text"], ["widget_name", "text"]]
