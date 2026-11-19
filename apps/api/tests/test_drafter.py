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


def test_a_filled_dataset_takes_the_models_time_column_only_among_its_time_columns(files):
    files.merge_drafts("datasets.yaml", [{
        "id": "staff", "description": "Description to draft.", "grain": "one row per person", "time_column": "born_on",
        "evidence": [{"kind": "profile", "ref": "widget_sales.widget_name"}], "confidence": 0.5,
        "columns": [{"name": "born_on", "type": "date", "role": "time", "description": "Description to draft."},
                    {"name": "hired_on", "type": "date", "role": "time", "description": "Description to draft."}],
    }])
    reply = {"id": "staff", "description": "Staff.", "grain": "one row per person", "confidence": 0.8, "evidence": [],
             "columns": [{"name": "hired_on", "type": "date", "role": "time", "description": "Hire day."}]}

    [hired] = Drafter(FakeLLMClient([{"items": [{**reply, "time_column": "hired_on"}]}]), Warehouse()).draft(
        "datasets.yaml", files, PROFILE, [])
    [kept] = Drafter(FakeLLMClient([{"items": [{**reply, "time_column": "nowhere"}]}]), Warehouse()).draft(
        "datasets.yaml", files, PROFILE, [])

    assert hired["time_column"] == "hired_on" and kept["time_column"] == "born_on"
    # The reply cited nothing known, so the item keeps the evidence it had instead of another table's profile.
    assert hired["evidence"] == [{"kind": "profile", "ref": "widget_sales.widget_name"}]


def test_a_new_dataset_is_held_to_the_pack_rules_instead_of_failing_the_compile(files):
    # A reply for a table without dates: a number marked indexable and a time column that is not a time column.
    llm = FakeLLMClient([{"items": [{
        "id": "catalog", "description": "Every catalog item.", "grain": "one row per item", "time_column": "item_no",
        "evidence": [{"kind": "profile", "ref": "widget_sales"}], "confidence": 0.8,
        "columns": [
            {"name": "item_no", "type": "number", "role": "dimension", "description": "Item number.", "indexable": True},
            {"name": "colour", "type": "string", "role": "dimension", "description": "Colour.", "indexable": True},
        ],
    }]}])

    [item] = Drafter(llm, Warehouse()).draft("datasets.yaml", files, PROFILE, [])

    assert "time_column" not in item
    assert [column.get("indexable", False) for column in item["columns"]] == [False, True]


def test_drafted_ids_and_references_are_made_valid_instead_of_failing_the_pack(files):
    llm = FakeLLMClient([{"items": [metric("sumIf_amount_status"), metric("Revenue-Total 2025"), metric("2nd_metric")]}])

    items = Drafter(llm, Warehouse()).draft("metrics.yaml", files, PROFILE, CHUNKS)

    assert [item["id"] for item in items] == ["sum_if_amount_status", "revenue_total_2025", "m_2nd_metric"]


def test_metric_references_of_examples_follow_the_same_ids(files):
    llm = FakeLLMClient([{"items": [{
        "id": "OrdersPerMonth", "question": "Orders per month?", "language": "en", "sql": "SELECT 1",
        "datasets": ["widget_sales"], "metrics": ["sumIf_amount_status"],
        "evidence": [{"kind": "profile", "ref": "widget_sales"}], "confidence": 0.6,
    }]}])

    [item] = Drafter(llm, Warehouse()).draft("examples.yaml", files, PROFILE, CHUNKS)

    assert (item["id"], item["metrics"]) == ("orders_per_month", ["sum_if_amount_status"])
