"""The Review and Datasets endpoints over a ReviewService on a temporary pack copy."""

from fastapi.testclient import TestClient
import pytest

from agent_fixtures import compiled_fixture
from auth_fixtures import token, verifier
from test_review_service import NOW, Warehouse, add_draft_metric, pack_dir, registry  # noqa: F401 - fixtures

from app.api import runtime
from app.data.clickhouse import QueryLimits
from app.main import app
from app.onboarding.review import ReviewService

REVIEWER = {"Authorization": f"Bearer {token(realm_access={'roles': ['pack_reviewer']})}"}
VIEWER = {"Authorization": f"Bearer {token()}"}


@pytest.fixture
def client(pack_dir, registry):  # noqa: F811 - pytest fixtures
    def service():
        return ReviewService(
            pack="minimal", pack_dir=pack_dir, registry=registry, warehouse=Warehouse(failing="cost_amount"),
            limits=QueryLimits(), compiled_dir=pack_dir.parents[1] / "build", clock=lambda: NOW,
        )

    app.dependency_overrides[runtime.get_verifier] = lambda: verifier()
    app.dependency_overrides[runtime.get_compiled] = lambda: compiled_fixture()
    app.dependency_overrides[runtime.get_review_service] = service
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_list_filters_by_file_and_status(client, pack_dir):  # noqa: F811
    add_draft_metric(pack_dir)
    response = client.get("/review/items", headers=REVIEWER, params={"file": "metrics.yaml", "status": "draft"})
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == ["metrics.gross_margin"]
    assert response.json()[0]["evidence"] == {"source": "gone.pdf", "quote": None, "deleted": True}


def test_edit_approve_test_run_and_delete(client, pack_dir):  # noqa: F811
    add_draft_metric(pack_dir)
    edited = client.patch("/review/items/metrics.gross_margin", headers=REVIEWER, json={"body": "Margin."})
    assert edited.status_code == 200 and edited.json()["body"] == "Margin."

    tested = client.post("/review/items/metrics.gross_margin/test-run", headers=REVIEWER)
    assert tested.status_code == 200 and tested.json()["test_result"]["rows"] == [[1234.5]]

    approved = client.post("/review/items/metrics.gross_margin/approve", headers=REVIEWER)
    assert approved.status_code == 200 and approved.json()["status"] == "approved"

    assert client.delete("/review/items/metrics.gross_margin", headers=REVIEWER).status_code == 204
    assert client.delete("/review/items/metrics.gross_margin", headers=REVIEWER).status_code == 404


def test_a_failing_formula_is_not_approved(client, pack_dir):  # noqa: F811
    add_draft_metric(pack_dir, sql_expr="sum(cost_amount)")
    response = client.post("/review/items/metrics.gross_margin/approve", headers=REVIEWER)
    assert response.status_code == 422 and "test-run failed" in response.json()["detail"]


def test_a_change_that_breaks_the_schema_is_refused(client):
    response = client.patch("/review/items/metrics.widget_revenue", headers=REVIEWER, json={"body": ""})
    assert response.status_code == 422 and "description" in response.json()["detail"]


@pytest.mark.parametrize(("method", "path"), [
    ("GET", "/review/items"), ("PATCH", "/review/items/metrics.widget_revenue"),
    ("POST", "/review/items/metrics.widget_revenue/approve"), ("POST", "/review/items/metrics.widget_revenue/test-run"),
    ("DELETE", "/review/items/metrics.widget_revenue"), ("GET", "/datasets"),
])
def test_only_a_pack_reviewer_reaches_review_and_datasets(client, method, path):
    assert client.request(method, path, headers=VIEWER, json={}).status_code == 403


def test_datasets_list_columns_and_the_roles_granted_each(client):
    response = client.get("/datasets", headers=REVIEWER)
    assert response.status_code == 200
    by_id = {dataset["id"]: dataset for dataset in response.json()}
    sales = by_id["widget_sales"]
    assert sales["readable_roles"] == ["viewer"] and sales["time_column"] == "sold_on"
    assert sales["columns"][0] == {"name": "sale_ref", "type": "string", "role": "dimension", "description": "Sale key."}
