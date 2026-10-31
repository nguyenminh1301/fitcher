"""Compile the fixture pack against fake ClickHouse, OpenSearch and embeddings."""

from datetime import UTC, date, datetime
import json
from pathlib import Path

from conftest import SCHEMA_DIR, fixture_catalog
from fakes import FakeEmbeddings, FakeSearch, FakeWarehouse
import pytest

from app.packs.compiler import (
    CompileError,
    approved_pack,
    check_metric_expression,
    compile_pack,
    load_compiled,
    read_coverage,
)
from app.packs.loader import PackValidationError, load_pack
from app.packs.search_indices import INDEX_NAMES
from app.search.opensearch import SearchError

PACK = "minimal"


def warehouse(**kwargs) -> FakeWarehouse:
    return FakeWarehouse(
        fixture_catalog().tables,
        coverage={
            "widget_sales": (120, date(2023, 1, 2), date(2025, 6, 30)),
            "widget_refunds": (8, date(2023, 2, 1), date(2025, 5, 31)),
        },
        values={("widget_sales", "widget_name"): [("Blue Widget", 90), ("Red Widget", 30)]},
        **kwargs,
    )


def run(pack_dir: Path, tmp_path: Path, search: FakeSearch, embeddings=None, **kwargs):
    return compile_pack(
        pack_dir,
        warehouse=kwargs.pop("warehouse", None) or warehouse(),
        top_k=100,
        search=search,
        embeddings=embeddings or FakeEmbeddings(),
        output_dir=tmp_path / "build",
        schema_dir=SCHEMA_DIR,
        clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
        **kwargs,
    )


def test_first_compile_publishes_generation_one(pack_dir, tmp_path):
    search = FakeSearch()

    summary = run(pack_dir, tmp_path, search)

    assert summary.generation == 1
    assert summary.metrics_tested == ["widget_revenue", "refunded_value"]
    assert set(search.indices) == {f"{PACK}_{index}_v1" for index in INDEX_NAMES}
    assert search.aliases == {f"{PACK}_{index}": f"{PACK}_{index}_v1" for index in INDEX_NAMES}
    assert len(search.alias_updates) == 1
    assert summary.documents == {
        "glossary_terms": 2, "metrics": 2, "datasets": 10, "column_values": 2, "examples": 1, "kb_docs": 0,
    }
    assert "hybrid_search" in search.pipelines


def test_semantic_documents_carry_embeddings_and_values_do_not(pack_dir, tmp_path):
    search = FakeSearch()

    run(pack_dir, tmp_path, search, embeddings=FakeEmbeddings(dimensions=4))

    metric = search.documents[f"{PACK}_metrics_v1"][0]
    value = search.documents[f"{PACK}_column_values_v1"][0]
    assert len(metric["embedding"]) == 4 and "embedding_text" not in metric
    assert "embedding" not in value and value["title"] == "Blue Widget"
    assert search.indices[f"{PACK}_metrics_v1"]["mappings"]["properties"]["embedding"]["dimension"] == 4


def test_compiled_artifact_records_generation_and_coverage(pack_dir, tmp_path):
    run(pack_dir, tmp_path, FakeSearch())

    compiled = load_compiled(tmp_path / "build", PACK)

    assert compiled.generation == 1
    assert compiled.embedding_dimensions == 4
    assert compiled.coverage["widget_sales"].min_date == "2023-01-02"
    assert compiled.coverage["widget_sales"].max_date == "2025-06-30"
    assert compiled.compiled_at == "2026-01-01T00:00:00+00:00"
    assert compiled.pack.name == PACK


def test_recompile_moves_every_alias_in_one_request_then_deletes_the_old_generation(pack_dir, tmp_path):
    search = FakeSearch()
    run(pack_dir, tmp_path, search)

    summary = run(pack_dir, tmp_path, search)

    assert summary.generation == 2
    swap = search.alias_updates[-1]
    assert {action["remove"]["index"] for action in swap if "remove" in action} == {
        f"{PACK}_{index}_v1" for index in INDEX_NAMES
    }
    assert {action["add"]["index"] for action in swap if "add" in action} == {
        f"{PACK}_{index}_v2" for index in INDEX_NAMES
    }
    assert set(search.indices) == {f"{PACK}_{index}_v2" for index in INDEX_NAMES}
    assert load_compiled(tmp_path / "build", PACK).generation == 2


def test_failure_midway_deletes_the_partial_generation_and_keeps_live_aliases(pack_dir, tmp_path):
    search = FakeSearch()
    run(pack_dir, tmp_path, search)
    live = dict(search.aliases)
    search.fail_bulk_into = "_examples_v2"

    with pytest.raises(CompileError, match="building index generation 2 failed: bulk indexing into"):
        run(pack_dir, tmp_path, search)

    assert search.aliases == live
    assert set(search.indices) == {f"{PACK}_{index}_v1" for index in INDEX_NAMES}
    assert len(search.alias_updates) == 1
    assert load_compiled(tmp_path / "build", PACK).generation == 1
    assert not list((tmp_path / "build" / PACK).glob("*.tmp"))


def test_embedding_failure_deletes_the_partial_generation(pack_dir, tmp_path):
    search = FakeSearch()

    with pytest.raises(CompileError, match="embedding service unavailable"):
        run(pack_dir, tmp_path, search, embeddings=FakeEmbeddings(fail_after=3))

    assert search.indices == {}
    assert search.aliases == {}
    assert not (tmp_path / "build" / PACK / "compiled.json").exists()


def test_failed_cleanup_of_the_old_generation_keeps_the_compile_successful(pack_dir, tmp_path, monkeypatch):
    search = FakeSearch()
    run(pack_dir, tmp_path, search)

    def refuse(name):
        raise SearchError(f"DELETE /{name} returned HTTP 500")

    monkeypatch.setattr(search, "delete_index", refuse)
    summary = run(pack_dir, tmp_path, search)

    assert summary.generation == 2
    assert summary.warnings == [f"older index generations were not deleted: DELETE /{PACK}_column_values_v1 returned HTTP 500"]
    assert search.aliases == {f"{PACK}_{index}": f"{PACK}_{index}_v2" for index in INDEX_NAMES}


def test_scans_are_read_only_with_time_and_memory_limits(pack_dir, tmp_path):
    fake = warehouse()

    run(pack_dir, tmp_path, FakeSearch(), warehouse=fake)

    scans = [settings for sql, settings in fake.queries if "system.columns" in sql or "count(), min(" in sql or "toString(" in sql]
    assert len(scans) == 4
    assert all(settings == {"max_execution_time": 300, "max_memory_usage": 2_000_000_000, "readonly": 2} for settings in scans)


def test_failing_metric_aborts_with_its_id_and_the_clickhouse_error(pack_dir, tmp_path):
    search = FakeSearch()
    failing = warehouse(failures={"sum(refund_total)": "Code: 47. DB::Exception: Unknown identifier refund_total"})

    with pytest.raises(CompileError) as raised:
        run(pack_dir, tmp_path, search, warehouse=failing)

    assert "metric 'refunded_value': ClickHouse rejected sql_expr: Code: 47. DB::Exception" in str(raised.value)
    assert "widget_revenue" not in str(raised.value)
    assert search.indices == {}


def test_metric_test_run_is_read_only_with_a_time_limit(pack_dir, tmp_path):
    fake = warehouse()

    run(pack_dir, tmp_path, FakeSearch(), warehouse=fake)

    metric_queries = [(sql, settings) for sql, settings in fake.queries if sql.startswith("SELECT sum(")]
    assert metric_queries == [
        ("SELECT sum(sale_amount) FROM `marts`.`widget_sales` LIMIT 1", {"max_execution_time": 30, "readonly": 2}),
        ("SELECT sum(refund_total) FROM `marts`.`widget_refunds` LIMIT 1", {"max_execution_time": 30, "readonly": 2}),
    ]


def test_unparsable_metric_is_rejected_before_it_runs(pack_dir, edit_pack, tmp_path):
    edit_pack("metrics.yaml", lambda data: data["metrics"][0].update(sql_expr="sum(sale_amount"))
    fake = warehouse()

    with pytest.raises(CompileError, match="metric 'widget_revenue': sql_expr does not parse as one expression"):
        run(pack_dir, tmp_path, FakeSearch(), warehouse=fake)

    assert not any("sale_amount" in sql for sql, _ in fake.queries if sql.startswith("SELECT sum("))


@pytest.mark.parametrize("sql_expr", [
    "sum(x); DROP TABLE t",
    "DROP TABLE t",
    "(SELECT max(x) FROM t)",
    "sum(x) + (SELECT 1)",
    "",
])
def test_metric_expression_must_be_a_single_expression(sql_expr):
    with pytest.raises(ValueError):
        check_metric_expression(sql_expr)


@pytest.mark.parametrize("sql_expr", ["count()", "sumIf(a, b != 'x') / nullIf(uniqExactIf(c, b != 'x'), 0)"])
def test_metric_expression_accepts_aggregates(sql_expr):
    check_metric_expression(sql_expr)


def test_invalid_schema_is_rejected_with_file_and_path(pack_dir, edit_pack, tmp_path):
    edit_pack("metrics.yaml", lambda data: data["metrics"][0].update(unit="furlongs"))
    search = FakeSearch()

    with pytest.raises(PackValidationError, match=r"metrics\.yaml: metrics\[0\]\.unit"):
        run(pack_dir, tmp_path, search)

    assert search.indices == {}


def test_column_missing_from_the_warehouse_is_rejected(pack_dir, tmp_path):
    tables = fixture_catalog().tables
    tables["widget_sales"] = tables["widget_sales"] - {"widget_name"}

    with pytest.raises(PackValidationError, match="column 'widget_name' not found in table 'widget_sales'"):
        run(pack_dir, tmp_path, FakeSearch(), warehouse=FakeWarehouse(tables))


def test_skip_index_stops_after_the_metric_test_run(pack_dir, tmp_path):
    search = FakeSearch()
    embeddings = FakeEmbeddings()

    summary = run(pack_dir, tmp_path, search, embeddings=embeddings, skip_index=True)

    assert summary.generation is None
    assert summary.metrics_tested == ["widget_revenue", "refunded_value"]
    assert search.indices == {} and embeddings.calls == []


def test_draft_items_are_not_compiled(pack_dir, edit_pack):
    edit_pack("glossary.yaml", lambda data: data["terms"][1].update(status="draft"))

    pack = approved_pack(load_pack(pack_dir, schema_dir=SCHEMA_DIR))

    assert [term.id for term in pack.glossary.terms] == ["revenue"]


def test_approved_item_referencing_a_draft_item_is_rejected(pack_dir, edit_pack):
    edit_pack("metrics.yaml", lambda data: data["metrics"][0].update(status="draft"))

    with pytest.raises(CompileError, match=r"glossary\.yaml: terms\[0\]\.targets\[0\]\.metric: unknown metric"):
        approved_pack(load_pack(pack_dir, schema_dir=SCHEMA_DIR))


def test_empty_dataset_has_no_coverage_dates(pack_dir):
    pack = load_pack(pack_dir, schema_dir=SCHEMA_DIR)

    coverage = read_coverage(pack, FakeWarehouse(fixture_catalog().tables))

    assert coverage["widget_sales"].rows == 0
    assert coverage["widget_sales"].min_date is None


def test_compiled_json_is_valid_json(pack_dir, tmp_path):
    run(pack_dir, tmp_path, FakeSearch())

    data = json.loads((tmp_path / "build" / PACK / "compiled.json").read_text(encoding="utf-8"))

    assert data["coverage"]["widget_refunds"]["rows"] == 8
