"""Proposals in the Review page and the Feedback endpoints, over an in-memory proposal store."""

from dataclasses import replace
from datetime import UTC, datetime

from fastapi.testclient import TestClient
import pytest

from agent_fixtures import compiled_fixture
from session_fixtures import SessionHeaders
from test_review_service import NOW, Warehouse, pack_dir, registry  # noqa: F401 - fixtures

from app.api import runtime
from app.contracts.admin_feedback import FeedbackRow
from app.contracts.review import ReviewedSpec, SpecFilter
from app.data.clickhouse import QueryLimits
from app.feedback.proposals import Proposal, RunFacts
from app.main import app
from app.onboarding.pack_yaml import ItemNotFound, PackFiles
from app.onboarding.review import ReviewRefused, ReviewService

REVIEWER = SessionHeaders(['pack_reviewer'])
ADMIN = SessionHeaders(['admin'])
TS = datetime(2026, 11, 5, tzinfo=UTC)


def proposal(**overrides) -> Proposal:
    base = dict(proposal_id="abc123def4567890", pack="minimal", ts=TS, trace_id="t9",
                question="Revenue for [MASKED_EMAIL] in 2025", sql="SELECT sum(sale_amount) FROM marts.widget_sales "
                "WHERE buyer = '[MASKED_EMAIL]'", source="dislike", status="proposed",
                spec='{"metric_ids": ["widget_revenue"], "dataset": "widget_sales"}', error="", note="wrong total",
                confidence=0.5)
    return Proposal(**{**base, **overrides})


class Store:
    def __init__(self, items=(), runs=None, known=()):
        self.saved = list(items)
        self.runs = runs or {}
        self.known = set(known)

    def proposals(self, pack, open_only=True):
        latest = {}
        for item in self.saved:
            latest[item.proposal_id] = item
        return [item for item in latest.values() if not open_only or item.status == "proposed"]

    def save(self, item):
        self.saved.append(item)

    def run(self, pack, trace_id):
        return self.runs.get(trace_id)

    def known_questions(self, pack):
        return self.known

    def feedback(self, pack, rating, start, end):
        return [FeedbackRow(trace_id="t9", ts=TS, user_id="lab.analyst", rating="dislike", question="Revenue?",
                            note="wrong", run_status="succeeded", proposal="proposed")]


def service(pack_dir, registry, store, warehouse=None):  # noqa: F811
    return ReviewService(pack="minimal", pack_dir=pack_dir, registry=registry, warehouse=warehouse or Warehouse(),
                         limits=QueryLimits(), compiled_dir=pack_dir.parents[1] / "build", clock=lambda: NOW,
                         proposals=store)


def test_open_proposals_are_listed_next_to_pack_items(pack_dir, registry):  # noqa: F811
    store = Store([proposal(), proposal(proposal_id="gone", status="dismissed")])
    items = {item.id: item for item in service(pack_dir, registry, store).items(file="examples.yaml")}
    view = items["proposals.abc123def4567890"]
    assert (view.kind, view.status, view.formula.startswith("SELECT")) == ("proposal", "draft", True)
    assert view.evidence.model_dump() == {"source": "Trace t9", "quote": "wrong total", "deleted": False}
    assert "proposals.gone" not in items


def test_a_masked_proposal_is_not_approved(pack_dir, registry):  # noqa: F811
    review = service(pack_dir, registry, Store([proposal()]))
    with pytest.raises(ReviewRefused, match="masked value"):
        review.approve("proposals.abc123def4567890")


def test_an_edited_proposal_is_approved_into_examples_after_a_test_run(pack_dir, registry):  # noqa: F811
    store = Store([proposal()])
    review = service(pack_dir, registry, store)
    review.update("proposals.abc123def4567890", body="Revenue for widget buyers in 2025",
                  formula="SELECT sum(sale_amount) FROM marts.widget_sales")

    approved = review.approve("proposals.abc123def4567890")

    example = PackFiles(pack_dir).find("examples.yaml", "proposal_abc123def456")
    assert approved.status == "approved" and example["question"] == "Revenue for widget buyers in 2025"
    assert example["evidence"] == [{"kind": "trace", "ref": "t9"}]
    assert example["datasets"] == ["widget_sales"] and example["metrics"] == ["widget_revenue"]
    assert example["language"] == "en" and "note" not in example and "spec" not in example
    assert store.saved[-1].status == "approved"
    assert service(pack_dir, registry, store).items(file="examples.yaml")[-1].kind == "item"


RUN_SPEC = ('{"metric_ids": ["widget_revenue"], "dataset": "widget_sales", "dimensions": ["widget_name", "sold_on"], '
            '"filters": [{"column": "widget_name", "op": "=", "value": "[MASKED_EMAIL]"}], "top_n": 5, "rank_by": "widget_revenue"}')
CLEAN_SQL = "SELECT widget_name, sum(sale_amount) FROM marts.widget_sales GROUP BY widget_name"


def reviewed(**overrides) -> ReviewedSpec:
    base = dict(metric_ids=["widget_revenue"], dataset="widget_sales", dimensions=["widget_name"],
                filters=[SpecFilter(column="widget_name", op="in", values=["Blue Widget"])], top_n=5, rank_by="widget_revenue")
    return ReviewedSpec(**{**base, **overrides})


def test_a_proposal_offers_the_runs_spec_without_the_time_column_and_unreviewed(pack_dir, registry):  # noqa: F811
    view = service(pack_dir, registry, Store([proposal(spec=RUN_SPEC)])).items_by_id("proposals.abc123def4567890")

    assert view.spec_reviewed is False
    assert view.spec.dimensions == ["widget_name"]
    assert [(f.column, f.op, f.values) for f in view.spec.filters] == [("widget_name", "=", ["[MASKED_EMAIL]"])]
    assert (view.spec.top_n, view.spec.rank_by) == (5, "widget_revenue")


def test_a_reviewed_spec_is_approved_into_the_example(pack_dir, registry):  # noqa: F811
    store = Store([proposal(spec=RUN_SPEC)])
    review = service(pack_dir, registry, store)
    review.update("proposals.abc123def4567890", body="Top 5 blue widgets by revenue", formula=CLEAN_SQL, spec=reviewed())

    review.approve("proposals.abc123def4567890")

    example = PackFiles(pack_dir).find("examples.yaml", "proposal_abc123def456")
    assert example["spec"] == {"dimensions": ["widget_name"], "filters": [{"column": "widget_name", "op": "in", "values": ["Blue Widget"]}],
                               "top_n": 5, "rank_by": "widget_revenue"}
    assert example["datasets"] == ["widget_sales"] and example["metrics"] == ["widget_revenue"]


def test_an_unreviewed_spec_stays_out_of_the_example(pack_dir, registry):  # noqa: F811
    review = service(pack_dir, registry, Store([proposal(spec=RUN_SPEC)]))
    review.update("proposals.abc123def4567890", body="Top 5 widgets by revenue", formula=CLEAN_SQL, spec=reviewed())
    review.update("proposals.abc123def4567890", spec_reviewed=False)

    review.approve("proposals.abc123def4567890")

    assert "spec" not in PackFiles(pack_dir).find("examples.yaml", "proposal_abc123def456")


class EmptyValues(Warehouse):
    """Finds no row for a filter value check."""

    def query_table(self, sql, settings=None):
        names, types, rows = super().query_table(sql, settings)
        return (names, types, []) if "LIMIT 1" in sql and "WHERE" in sql else (names, types, rows)


@pytest.mark.parametrize(("spec", "message"), [
    (reviewed(metric_ids=["refunded_value"], rank_by=None), "metric 'refunded_value' is computed from dataset 'widget_refunds'"),
    (reviewed(dimensions=["refund_total"]), "unknown column 'refund_total' in dataset 'widget_sales'"),
    (reviewed(filters=[SpecFilter(column="widget_name", op="=", values=["A", "B"])]), "operator '=' takes exactly one value"),
    (reviewed(filters=[SpecFilter(column="widget_name", op="=", values=["[MASKED_EMAIL]"])]), "masked value"),
    (reviewed(rank_by="refunded_value"), "rank_by must be one of the spec's metrics"),
])
def test_a_wrong_reviewed_spec_is_not_approved(pack_dir, registry, spec, message):  # noqa: F811
    review = service(pack_dir, registry, Store([proposal(spec=RUN_SPEC)]))
    review.update("proposals.abc123def4567890", body="Top widgets", formula=CLEAN_SQL, spec=spec)

    with pytest.raises(ReviewRefused, match=message):
        review.approve("proposals.abc123def4567890")


def test_a_filter_value_missing_from_the_data_is_not_approved(pack_dir, registry):  # noqa: F811
    review = service(pack_dir, registry, Store([proposal(spec=RUN_SPEC)]), EmptyValues())
    review.update("proposals.abc123def4567890", body="Top widgets", formula=CLEAN_SQL, spec=reviewed())

    with pytest.raises(ReviewRefused, match="'Blue Widget' is not a value of widget_sales.widget_name"):
        review.approve("proposals.abc123def4567890")


def test_a_failing_proposal_sql_is_not_approved(pack_dir, registry):  # noqa: F811
    store = Store([proposal(question="Revenue in 2025", sql="SELECT broken")])
    review = service(pack_dir, registry, store, Warehouse(failing="broken"))
    with pytest.raises(ReviewRefused, match="test-run failed"):
        review.approve("proposals.abc123def4567890")


def test_deleting_a_proposal_dismisses_it(pack_dir, registry):  # noqa: F811
    store = Store([proposal()])
    review = service(pack_dir, registry, store)
    review.delete("proposals.abc123def4567890")
    assert store.saved[-1].status == "dismissed"
    with pytest.raises(ItemNotFound):
        review.items_by_id("proposals.abc123def4567890")


# Feedback endpoints

RUN = RunFacts(trace_id="t9", pack="minimal", question="Revenue for a@b.co", status="succeeded", intent="data_query",
               error="", spec={"metric_ids": ["widget_revenue"]}, sql="SELECT 1", rating="dislike", note="")


@pytest.fixture
def client():
    app.dependency_overrides[runtime.get_compiled_or_none] = lambda: compiled_fixture()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_feedback_is_listed_for_a_reviewer(client):
    app.dependency_overrides[runtime.get_proposal_store] = lambda: Store()
    response = client.get("/admin/feedback", headers=REVIEWER, params={"rating": "dislike"})
    assert response.status_code == 200 and response.json()[0]["proposal"] == "proposed"
    assert client.get("/admin/feedback", headers=ADMIN).status_code == 403


def test_proposing_from_one_run(client):
    store = Store(runs={"t9": RUN, "t8": replace(RUN, trace_id="t8", status="denied")})
    app.dependency_overrides[runtime.get_proposal_store] = lambda: store

    proposed = client.post("/admin/feedback/t9/proposal", headers=REVIEWER).json()
    refused = client.post("/admin/feedback/t8/proposal", headers=REVIEWER).json()

    assert proposed["proposed"] is True and proposed["question"] == "Revenue for [MASKED_EMAIL]"
    assert refused == {"proposed": False, "proposal_id": None, "question": None, "reason": "the run was denied"}
    assert client.post("/admin/feedback/nope/proposal", headers=REVIEWER).status_code == 404
