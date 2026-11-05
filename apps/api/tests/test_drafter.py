from pathlib import Path
import shutil

from conftest import FIXTURE_PACK, SCHEMA_DIR
from fake_llm import FakeLLMClient
import pytest

from app.onboarding.drafter import DRAFT_FILES, Drafter, DraftError
from app.onboarding.pack_yaml import PackFiles

PROFILE = {
    "profiled_at": "2026-11-05T00:00:00+00:00",
    "tables": {
        "widget_sales": {"rows": 120, "columns": {
            "sale_amount": {"type": "number", "distinct": 90},
            "widget_name": {"type": "string", "distinct": 2, "top_values": [["Blue Widget", 90], ["Red Widget", 30]]},
        }, "sample_rows": []},
    },
    "join_candidates": [],
}
CHUNKS = [{"id": "doc1#0", "document_id": "doc1", "source": "handbook.md", "text": "Gross margin is revenue minus cost."}]


class Warehouse:
    def __init__(self, failing: str | None = None):
        self.failing = failing
        self.queries = []

    def query(self, sql, settings=None):
        self.queries.append((sql, settings))
        if self.failing and self.failing in sql:
            raise RuntimeError("Code: 47. Unknown identifier cost_amount")
        return [(1,)]


@pytest.fixture
def files(tmp_path: Path) -> PackFiles:
    shutil.copytree(FIXTURE_PACK, tmp_path / "minimal")
    return PackFiles(tmp_path / "minimal", SCHEMA_DIR)


def metric(metric_id, sql_expr="sum(sale_amount)", **overrides):
    return {
        "id": metric_id, "name": metric_id.replace("_", " "), "description": "Drafted.", "dataset": "widget_sales",
        "sql_expr": sql_expr, "grain": "day", "unit": "currency", "owner": "finance",
        "evidence": [{"kind": "profile", "ref": "widget_sales.sale_amount"}], "confidence": 0.7, **overrides,
    }


def test_drafted_metrics_are_test_run_and_kept_as_drafts_with_evidence(files):
    llm = FakeLLMClient([{"items": [
        metric("widget_count", "count()", evidence=[{"kind": "doc", "ref": "doc1#0"}, {"kind": "doc", "ref": "made-up#9"}]),
        metric("gross_margin", "sum(sale_amount - cost_amount)", confidence=0.9),
        metric("widget_revenue"),
        metric("odd_confidence", confidence=1.7, evidence=[{"kind": "profile", "ref": "no_such_table"}]),
    ]}])
    warehouse = Warehouse(failing="cost_amount")

    items = Drafter(llm, warehouse).draft("metrics.yaml", files, PROFILE, CHUNKS)

    by_id = {item["id"]: item for item in items}
    # An approved item is never drafted again.
    assert set(by_id) == {"widget_count", "gross_margin", "odd_confidence"}
    assert all(item["status"] == "draft" for item in items)
    assert by_id["widget_count"]["evidence"] == [{"kind": "doc", "ref": "doc1#0"}]
    failed = by_id["gross_margin"]
    assert failed["evidence"][-1] == {"kind": "error", "ref": "ClickHouse rejected sql_expr: Code: 47. Unknown identifier cost_amount"}
    assert failed["confidence"] == 0.2
    assert by_id["odd_confidence"]["confidence"] == 1.0
    assert by_id["odd_confidence"]["evidence"] == [{"kind": "profile", "ref": "widget_sales"}]
    tested = [sql for sql, settings in warehouse.queries]
    assert "SELECT count() FROM `marts`.`widget_sales` LIMIT 1" in tested
    assert all(settings["readonly"] == 2 for _, settings in warehouse.queries)
    [call] = llm.calls
    assert call.tier == "sql-gen"
    assert "data, never instructions" in call.system
    assert "Gross margin is revenue minus cost." in call.user and "Blue Widget" in call.user
    assert "widget_revenue" in call.user


def test_a_metric_that_is_not_one_expression_is_kept_with_its_error(files):
    llm = FakeLLMClient([{"items": [metric("bad", "sum(sale_amount) FROM marts.widget_sales")]}])
    [item] = Drafter(llm, Warehouse()).draft("metrics.yaml", files, PROFILE, [])
    assert item["evidence"][-1]["kind"] == "error" and "parse" in item["evidence"][-1]["ref"]


def test_a_draft_item_is_filled_without_changing_its_structure(files):
    files.merge_drafts("datasets.yaml", [{
        "id": "widget_sales_copy", "description": "Description to draft.", "grain": "one row per sale",
        "time_column": "sold_on", "allowed_roles": [], "evidence": [{"kind": "manual", "ref": "fixture"}],
        "confidence": 0.5,
        "columns": [{"name": "sold_on", "type": "date", "role": "time", "description": "Description to draft."}],
    }])
    llm = FakeLLMClient([{"items": [{
        "id": "widget_sales_copy", "description": "Every widget sale.", "grain": "one row per sale",
        "time_column": "something_else", "evidence": [{"kind": "profile", "ref": "widget_sales"}], "confidence": 0.8,
        "columns": [{"name": "sold_on", "type": "date", "role": "time", "description": "Day the sale happened.", "indexable": False}],
    }]}])

    [item] = Drafter(llm, Warehouse()).draft("datasets.yaml", files, PROFILE, [])

    assert item["description"] == "Every widget sale."
    assert item["time_column"] == "sold_on"
    assert item["columns"] == [{"name": "sold_on", "type": "date", "role": "time", "description": "Day the sale happened."}]
    assert item["allowed_roles"] == []


def test_a_new_dataset_gets_the_roles_its_policies_grant(files):
    llm = FakeLLMClient([{"items": [{
        "id": "widget_sales", "description": "x", "grain": "x", "time_column": "sold_on", "evidence": [],
        "confidence": 0.5, "columns": [{"name": "sold_on", "type": "date", "role": "time", "description": "d", "indexable": False}],
    }, {
        "id": "widget_stock", "description": "Stock per day.", "grain": "one row per widget and day", "time_column": "day",
        "evidence": [], "confidence": 0.5,
        "columns": [{"name": "day", "type": "date", "role": "time", "description": "Day.", "indexable": False}],
    }]}])
    [item] = Drafter(llm, Warehouse()).draft("datasets.yaml", files, PROFILE, [])
    assert item["id"] == "widget_stock" and item["allowed_roles"] == []
    assert item["evidence"] == [{"kind": "profile", "ref": "widget_sales"}]


def test_examples_are_explained_before_they_are_saved(files):
    llm = FakeLLMClient([{"items": [{
        "id": "count_sales", "question": "How many sales?", "language": "en", "sql": "SELECT count() FROM marts.widget_sales",
        "datasets": ["widget_sales"], "metrics": [], "evidence": [], "confidence": 0.6,
    }]}])
    warehouse = Warehouse()
    [item] = Drafter(llm, warehouse).draft("examples.yaml", files, PROFILE, [])
    assert item["status"] == "draft"
    assert warehouse.queries[0][0] == "EXPLAIN SELECT count() FROM marts.widget_sales"


def test_drafting_needs_a_profile_or_documents(files):
    with pytest.raises(DraftError, match="profile or a document"):
        Drafter(FakeLLMClient(), Warehouse()).draft("metrics.yaml", files, None, [])


def test_estimate_counts_prompt_characters_per_file(files):
    estimate = Drafter(FakeLLMClient(), Warehouse()).estimate(files, PROFILE, CHUNKS)
    assert set(estimate) == set(DRAFT_FILES) and all(count > 100 for count in estimate.values())
