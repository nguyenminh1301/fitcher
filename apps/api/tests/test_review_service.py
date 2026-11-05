from datetime import UTC, datetime
from pathlib import Path
import shutil

from conftest import FIXTURE_PACK, SCHEMA_DIR
import pytest

from app.data.clickhouse import QueryLimits
from app.onboarding.documents import DocumentRecord, InMemoryDocumentRegistry, compile_lock_path
from app.onboarding.pack_yaml import ItemNotFound, PackFiles
from app.onboarding.review import ReviewRefused, ReviewService

NOW = datetime(2026, 11, 5, tzinfo=UTC)


class Warehouse:
    """Answers table queries with one row; a query containing ``failing`` raises."""

    def __init__(self, failing: str | None = None):
        self.failing = failing
        self.queries = []

    def query_table(self, sql, settings=None):
        self.queries.append((sql, settings))
        if self.failing and self.failing in sql:
            raise RuntimeError("Code: 47. Unknown identifier")
        return ["value"], ["Float64"], [(1234.5,)]


def document(document_id: str, deleted: bool = False) -> DocumentRecord:
    return DocumentRecord(
        id=document_id, pack="minimal", file_name=f"{document_id}.pdf", media_type="application/pdf", size_bytes=1,
        sha256=document_id, uploaded_by="u", allowed_roles=["viewer"], status="indexed", uploaded_at=NOW,
        updated_at=NOW, deleted_at=NOW if deleted else None,
    )


@pytest.fixture
def pack_dir(tmp_path: Path) -> Path:
    shutil.copytree(FIXTURE_PACK, tmp_path / "packs" / "minimal")
    shutil.copytree(SCHEMA_DIR, tmp_path / "packs" / "_schema")
    return tmp_path / "packs" / "minimal"


@pytest.fixture
def registry():
    registry = InMemoryDocumentRegistry()
    registry.write(document("kept"))
    registry.write(document("gone", deleted=True))
    return registry


def service(pack_dir, registry, warehouse=None, tmp_path=None):
    return ReviewService(
        pack="minimal", pack_dir=pack_dir, registry=registry, warehouse=warehouse or Warehouse(),
        limits=QueryLimits(), compiled_dir=pack_dir.parents[1] / "build", clock=lambda: NOW,
    )


def add_draft_metric(pack_dir, sql_expr="sum(sale_amount)", evidence=None):
    files = PackFiles(pack_dir)
    files.merge_drafts("metrics.yaml", [{
        "id": "gross_margin", "name": "Gross margin", "description": "Sales minus cost.", "dataset": "widget_sales",
        "sql_expr": sql_expr, "grain": "day", "unit": "currency", "owner": "finance",
        "evidence": evidence or [{"kind": "doc", "ref": "gone#2"}, {"kind": "profile", "ref": "widget_sales"}],
        "confidence": 0.6,
    }])
    files.save("metrics.yaml")


def test_items_cover_every_file_and_map_their_text_and_formula(pack_dir, registry):
    add_draft_metric(pack_dir)
    items = {item.id: item for item in service(pack_dir, registry).items()}

    metric = items["metrics.gross_margin"]
    assert (metric.file, metric.name, metric.status, metric.kind) == ("metrics.yaml", "gross_margin", "draft", "item")
    assert metric.body == "Sales minus cost." and metric.formula == "sum(sale_amount)" and metric.confidence == 0.6
    assert metric.evidence.model_dump() == {"source": "gone.pdf", "quote": None, "deleted": True}
    assert [ref.model_dump() for ref in metric.evidence_refs] == [
        {"kind": "doc", "ref": "gone#2"}, {"kind": "profile", "ref": "widget_sales"},
    ]
    term = items["glossary.revenue"]
    assert term.file == "glossary.yaml" and term.formula is None and term.body
    assert items["datasets.widget_sales"].evidence.model_dump() == {"source": "fixture", "quote": None, "deleted": False}
    assert "examples.revenue_by_widget" in items and items["examples.revenue_by_widget"].formula.startswith("SELECT")


def test_items_filter_by_file_and_status(pack_dir, registry):
    add_draft_metric(pack_dir)
    review = service(pack_dir, registry)
    assert [item.id for item in review.items(file="metrics.yaml", status="draft")] == ["metrics.gross_margin"]
    assert all(item.file == "datasets.yaml" for item in review.items(file="datasets.yaml"))


def test_an_edit_returns_an_approved_item_to_draft(pack_dir, registry):
    review = service(pack_dir, registry)
    item = review.update("metrics.widget_revenue", body="Paid amount.", formula="sum(sale_amount) * 1")
    assert (item.status, item.body, item.formula) == ("draft", "Paid amount.", "sum(sale_amount) * 1")
    assert "status: draft" in (pack_dir / "metrics.yaml").read_text(encoding="utf-8")


def test_a_formula_on_an_item_without_one_is_refused(pack_dir, registry):
    with pytest.raises(ReviewRefused, match="has no formula"):
        service(pack_dir, registry).update("glossary.revenue", formula="sum(x)")


def test_approve_test_runs_a_metric_first(pack_dir, registry):
    add_draft_metric(pack_dir, sql_expr="sum(cost_amount)")
    review = service(pack_dir, registry, Warehouse(failing="cost_amount"))
    with pytest.raises(ReviewRefused, match="test-run failed"):
        review.approve("metrics.gross_margin")
    assert review.items(file="metrics.yaml", status="draft")[0].id == "metrics.gross_margin"

    review = service(pack_dir, registry)
    assert review.approve("metrics.gross_margin").status == "approved"


def test_test_run_returns_a_result_with_the_review_limits(pack_dir, registry):
    warehouse = Warehouse()
    item = service(pack_dir, registry, warehouse).test_run("metrics.widget_revenue")
    assert item.test_result.rows == [[1234.5]]
    assert item.test_result.columns[0].model_dump() == {"name": "value", "type": "number", "role": "measure", "format": None}
    sql, settings = warehouse.queries[0]
    assert sql == "SELECT sum(sale_amount) AS value FROM `marts`.`widget_sales` LIMIT 1"
    assert settings["readonly"] == 2 and settings["max_execution_time"] == 30 and settings["max_result_rows"] == 100


def test_an_item_without_a_formula_has_nothing_to_test_run(pack_dir, registry):
    with pytest.raises(ReviewRefused, match="nothing to test-run"):
        service(pack_dir, registry).test_run("glossary.revenue")


def test_delete_and_unknown_ids(pack_dir, registry):
    add_draft_metric(pack_dir)
    review = service(pack_dir, registry)
    review.delete("metrics.gross_margin")
    with pytest.raises(ItemNotFound):
        review.delete("metrics.gross_margin")
    with pytest.raises(ItemNotFound):
        review.items_by_id("unknown.thing")


def test_changes_wait_while_the_pack_compiles(pack_dir, registry):
    lock = compile_lock_path(pack_dir.parents[1] / "build", "minimal")
    lock.parent.mkdir(parents=True)
    lock.write_text(NOW.isoformat(), encoding="utf-8")
    with pytest.raises(ReviewRefused, match="compiling") as raised:
        service(pack_dir, registry).approve("metrics.widget_revenue")
    assert raised.value.status == 409
