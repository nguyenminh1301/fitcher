"""The instant pack pipeline: marts, profile, files, draft, approve, compile and activate as one job (DECISIONS §11)."""

from pathlib import Path
import shutil

from conftest import SCHEMA_DIR
import pytest
import yaml

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


def _pipeline(packs_dir, drafter=None, compile_fails=False, model_missing=None, client=None, compile_error=None):
    compiled, activated = [], []

    def compile_pack(pack_dir: Path, progress=None):
        compiled.append(pack_dir.name)
        if progress is not None:
            progress("screen", 0, 1200)
            progress("index", 500, 1200)
        if compile_error is not None:
            raise compile_error
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
    compile_step = next(step for step in job.steps if step["id"] == "compile")
    assert (compile_step["phase"], compile_step["done"], compile_step["total"]) == ("index", 500, 1200)
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


def test_a_step_clickhouse_refused_reports_a_reason_and_never_its_text_with_the_data(packs_dir, caplog):
    refusal = RuntimeError("Code: 36. DB::Exception: Cannot parse PostgreSQL value '123456789012345678901234.5678' "
                           "as Decimal(38, 19): Decimal value is too big. (BAD_ARGUMENTS)")
    pipeline, _, _ = _pipeline(packs_dir, compile_error=refusal)

    job = pipeline.run(pipeline.new_job("shop", ["widgets", "sales"], started_by="owner"))

    assert (job.status, job.failed_step, job.error_reason) == ("failed", "compile", "value_out_of_range")
    assert "1234567890" not in job.error and "Decimal(38, 19)" not in job.error
    assert job.had_pack is False
    assert "123456789012345678901234.5678" in caplog.text, "the full text stays in the log"


def test_a_build_knows_whether_a_previous_pack_keeps_answering(packs_dir):
    (packs_dir / "shop").mkdir()
    pipeline, _, _ = _pipeline(packs_dir, compile_fails=True)

    job = pipeline.run(pipeline.new_job("shop", ["widgets", "sales"], started_by="owner"))

    assert job.had_pack is True and job.error_reason is None, "an error that is not ClickHouse's keeps its text"


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


def test_wide_views_are_profiled_from_their_tables_without_scanning_a_join():
    from app.onboarding.instant import wide_profiles
    from app.onboarding.marts import MartTable, SourceColumn, plan_marts

    widgets = MartTable(name="widgets", relation="`raw`.`shop__widgets`", live=False, primary_key=("widget_id",),
                        columns=(SourceColumn("widget_id", "Int64"), SourceColumn("widget_name", "String")))
    sales = MartTable(name="sales", relation="`raw`.`shop__sales`", live=False,
                      columns=(SourceColumn("sale_id", "Int64"), SourceColumn("widget_id", "Int64")),
                      foreign_keys=(ForeignKey(("widget_id",), "widgets", ("widget_id",)),))
    views = plan_marts("shop", [widgets, sales])
    profile = {"tables": {
        "shop__widgets": {"rows": 3, "columns": {"widget_id": {"type": "number", "distinct": 3},
                                                 "widget_name": {"type": "string", "distinct": 3, "top_values": [["A", 1]]}},
                          "sample_rows": []},
        "shop__sales": {"rows": 9, "columns": {"sale_id": {"type": "number", "distinct": 9}, "widget_id": {"type": "number", "distinct": 3}},
                        "sample_rows": [[1, 2]]},
    }, "join_candidates": []}

    profiled = wide_profiles(views, profile)

    wide = profiled["tables"]["shop__sales__wide"]
    assert wide["rows"] == 9
    assert wide["columns"] == {"sale_id": {"type": "number", "distinct": 9}, "widget_id": {"type": "number", "distinct": 3},
                               "widgets_widget_name": {"type": "string", "distinct": 3, "top_values": [["A", 1]]}}
    assert wide["sample_rows"] == []
    assert set(profiled["tables"]) == {"shop__widgets", "shop__sales", "shop__sales__wide"}


def test_a_draft_without_metrics_is_asked_once_more_then_gets_counts_and_totals(packs_dir):
    drafter = FakeDrafter()
    pipeline, _, _ = _pipeline(packs_dir, drafter=drafter)

    job = pipeline.run(pipeline.new_job("shop", ["widgets", "sales"], started_by="owner"))

    assert job.status == "succeeded"
    assert drafter.calls.count("metrics.yaml") == 2
    metrics = {item["id"]: item for item in yaml.safe_load((packs_dir / "shop" / "metrics.yaml").read_text())["metrics"]}
    assert metrics["shop__sales_rows"]["sql_expr"] == "count()"
    assert metrics["shop__sales_sale_amount_total"]["sql_expr"] == "sum(sale_amount)"
    assert {item["status"] for item in metrics.values()} == {"approved"}
    assert all(item["dataset"] in ("shop__widgets", "shop__sales", "shop__sales__wide") for item in metrics.values())


def test_drafted_metrics_are_kept_without_a_second_draft(packs_dir):
    class WithMetric(FakeDrafter):
        def draft(self, file, files, profile, chunks):
            if file != "metrics.yaml":
                return super().draft(file, files, profile, chunks)
            self.calls.append(file)
            return [{"id": "revenue", "name": "Revenue", "description": "Sales.", "dataset": "shop__sales", "sql_expr": "sum(amount)",
                     "grain": "day", "unit": "currency", "owner": "finance", "evidence": [{"kind": "profile", "ref": "shop__sales"}],
                     "confidence": 0.6, "status": "draft"}]

    drafter = WithMetric()
    pipeline, _, _ = _pipeline(packs_dir, drafter=drafter)

    pipeline.run(pipeline.new_job("shop", ["widgets", "sales"], started_by="owner"))

    assert drafter.calls.count("metrics.yaml") == 1
    ids = [item["id"] for item in yaml.safe_load((packs_dir / "shop" / "metrics.yaml").read_text())["metrics"]]
    assert ids == ["revenue"]


def test_a_drafted_item_the_schema_rejects_is_dropped_and_named_instead_of_failing_the_pack(packs_dir):
    class BrokenTerm(FakeDrafter):
        def draft(self, file, files, profile, chunks):
            if file != "glossary.yaml":
                return super().draft(file, files, profile, chunks)
            self.calls.append(file)
            term = {"term": "Revenue", "definition": "Money in.", "aliases": {"vi": ["doanh thu"], "en": ["sales"]},
                    "evidence": [{"kind": "profile", "ref": "shop__sales"}], "confidence": 0.5, "status": "draft"}
            return [{**term, "id": "revenue", "targets": [{"kind": "metric"}]},
                    {**term, "id": "sale_amount", "term": "Sale amount",
                     "targets": [{"kind": "column", "dataset": "shop__sales", "column": "sale_amount"}]}]

    pipeline, _, _ = _pipeline(packs_dir, drafter=BrokenTerm())

    job = pipeline.run(pipeline.new_job("shop", ["widgets", "sales"], started_by="owner"))

    assert job.status == "succeeded", job.error
    assert "glossary.revenue" in job.result["dropped"]
    terms = [item["id"] for item in yaml.safe_load((packs_dir / "shop" / "glossary.yaml").read_text())["terms"]]
    assert terms == ["sale_amount"]
