"""POST /feedback: a like or dislike with an optional note, accepted only for the user's own answer (§10, §15)."""

from fastapi.testclient import TestClient
import pytest

from agent_fixtures import compiled_fixture
from auth_fixtures import token, verifier
from fakes import FakeConversationClient

from app.api import runtime
from app.conversation.store import ConversationStore
from app.main import app

TRACE = "a" * 32


def headers(user: str = "lab.viewer") -> dict:
    return {"Authorization": f"Bearer {token(preferred_username=user)}"}


@pytest.fixture
def tables():
    return FakeConversationClient()


@pytest.fixture
def client(tables):
    store = ConversationStore(tables)
    turn = store.open_turn("lab.viewer", None, "Top widgets")
    store.answer(turn, trace_id=TRACE, content="Blue led.", query_spec=None, result=None)
    app.dependency_overrides[runtime.get_verifier] = lambda: verifier()
    app.dependency_overrides[runtime.get_compiled] = lambda: compiled_fixture()
    app.dependency_overrides[runtime.get_conversation_store] = lambda: store
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_a_like_with_a_note_is_written_to_feedback(client, tables):
    response = client.post("/feedback", json={"trace_id": TRACE, "rating": "dislike", "note": "Wrong quarter"}, headers=headers())

    assert response.status_code == 204
    [row] = tables.tables["feedback"]
    assert {key: row[key] for key in ("user_id", "trace_id", "rating", "note")} == {
        "user_id": "lab.viewer", "trace_id": TRACE, "rating": "dislike", "note": "Wrong quarter",
    }


def test_the_note_is_optional(client, tables):
    assert client.post("/feedback", json={"trace_id": TRACE, "rating": "like"}, headers=headers()).status_code == 204
    assert tables.tables["feedback"][0]["note"] == ""


def test_feedback_on_another_users_answer_is_rejected(client, tables):
    response = client.post("/feedback", json={"trace_id": TRACE, "rating": "like"}, headers=headers("lab.analyst"))

    assert response.status_code == 404
    assert tables.tables["feedback"] == []


def test_feedback_on_an_unknown_answer_is_rejected(client, tables):
    assert client.post("/feedback", json={"trace_id": "b" * 32, "rating": "like"}, headers=headers()).status_code == 404


@pytest.mark.parametrize("body", [{"trace_id": TRACE, "rating": "love"}, {"trace_id": "", "rating": "like"}, {"trace_id": TRACE, "rating": "like", "note": "x" * 1001}])
def test_an_invalid_body_is_422(client, body):
    assert client.post("/feedback", json=body, headers=headers()).status_code == 422


def test_feedback_needs_a_signed_in_user(client):
    assert client.post("/feedback", json={"trace_id": TRACE, "rating": "like"}).status_code == 401


def test_an_unreachable_store_is_503(client, tables):
    tables.fail = True

    assert client.post("/feedback", json={"trace_id": TRACE, "rating": "like"}, headers=headers()).status_code == 503
