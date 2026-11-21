"""``/settings/limits``: an admin reads and changes the questions answered at once."""

from fastapi.testclient import TestClient


from app.main import app

ADMIN = {}
VIEWER = {}


def test_the_question_limit_is_changed_within_its_range():
    client = TestClient(app)
    assert client.get("/settings/limits", headers=ADMIN).json() == {"concurrent_questions": 4}
    assert client.put("/settings/limits", headers=ADMIN, json={"concurrent_questions": 2}).status_code == 200
    assert client.get("/settings/limits", headers=ADMIN).json() == {"concurrent_questions": 2}
    assert client.put("/settings/limits", headers=ADMIN, json={"concurrent_questions": 0}).status_code == 422
