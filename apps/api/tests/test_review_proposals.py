"""Proposals in the Review page and the Feedback endpoints, over an in-memory proposal store."""

from dataclasses import replace
from datetime import UTC, datetime

from fastapi.testclient import TestClient
import pytest

from agent_fixtures import compiled_fixture
from auth_fixtures import token, verifier
from test_review_service import NOW, Warehouse, pack_dir, registry  # noqa: F401 - fixtures

from app.api import runtime
from app.contracts.admin_feedback import FeedbackRow
from app.data.clickhouse import QueryLimits
from app.feedback.proposals import Proposal, RunFacts
from app.main import app
from app.onboarding.pack_yaml import ItemNotFound, PackFiles
from app.onboarding.review import ReviewRefused, ReviewService

REVIEWER = {"Authorization": f"Bearer {token(realm_access={'roles': ['pack_reviewer']})}"}
ADMIN = {"Authorization": f"Bearer {token(realm_access={'roles': ['admin']})}"}
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
    app.dependency_overrides[runtime.get_verifier] = lambda: verifier()
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
