"""``/settings/limits``: an admin reads and changes the questions answered at once."""

from fastapi.testclient import TestClient

from session_fixtures import SessionHeaders

from app.main import app

ADMIN = SessionHeaders(["admin"])
VIEWER = SessionHeaders(["viewer"])


def test_an_admin_changes_the_question_limit_and_others_cannot():
    client = TestClient(app)
    assert client.get("/settings/limits", headers=ADMIN).json() == {"concurrent_questions": 4}
    assert client.put("/settings/limits", headers=ADMIN, json={"concurrent_questions": 2}).status_code == 200
    assert client.get("/settings/limits", headers=ADMIN).json() == {"concurrent_questions": 2}
    assert client.put("/settings/limits", headers=ADMIN, json={"concurrent_questions": 0}).status_code == 422
    assert client.put("/settings/limits", headers=VIEWER, json={"concurrent_questions": 9}).status_code == 403
