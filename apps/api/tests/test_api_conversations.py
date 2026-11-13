"""The conversation endpoints and edit/retry on /ask: each user sees and changes only their own conversations (§15)."""

import pytest
from fastapi.testclient import TestClient

from agent_fixtures import compiled_fixture
from session_fixtures import SessionHeaders
from fakes import FakeConversationClient
from pydantic import ValidationError
from test_api_ask import QUESTION, FakeAgent, answer, ask_with, kinds, parse

from app.api import runtime
from app.contracts.conversations import ConversationPatch
from app.contracts.events import AskRequest
from app.conversation.store import ConversationStore
from app.main import app


def headers(user: str = "lab.viewer") -> SessionHeaders:
    return SessionHeaders(user_id=user)


@pytest.fixture
def store():
    return ConversationStore(FakeConversationClient())


@pytest.fixture
def client(store):
    app.dependency_overrides[runtime.get_compiled] = lambda: compiled_fixture()
    app.dependency_overrides[runtime.get_conversation_store] = lambda: store
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def asked(store, user="lab.viewer", question="Doanh thu quý 1") -> str:
    turn = store.open_turn(user, None, question)
    store.question(turn)
    store.answer(turn, trace_id="t" * 32, content="Blue led.", query_spec=None, result=None)
    return turn.conversation_id


def test_list_search_and_read_a_thread(client, store):
    mine = asked(store)
    asked(store, question="Top widgets")
    asked(store, user="lab.analyst", question="Doanh thu của người khác")

    listed = client.get("/conversations", headers=headers()).json()
    found = client.get("/conversations/search", params={"q": "DOANH THU"}, headers=headers()).json()
    thread = client.get(f"/conversations/{mine}", headers=headers()).json()

    assert [item["title"] for item in listed] == ["Top widgets", "Doanh thu quý 1"]
    assert set(listed[0]) == {"id", "title", "pinned", "group_id", "updated_at"}
    assert [item["id"] for item in found] == [mine]
    assert thread["conversation"]["id"] == mine
    assert [(turn["turn"], turn["question"], [event["event"] for event in turn["events"]]) for turn in thread["turns"]] == [
        (1, "Doanh thu quý 1", ["summary", "done"]),
    ]


def test_the_list_pages_with_limit_and_offset(client, store):
    for number in range(3):
        asked(store, question=f"Question {number}")

    page = client.get("/conversations", params={"limit": 1, "offset": 1}, headers=headers()).json()

    assert [item["title"] for item in page] == ["Question 1"]
    assert client.get("/conversations", params={"limit": 500}, headers=headers()).status_code == 422


def test_rename_pin_group_and_delete(client, store):
    mine = asked(store)
    group = client.post("/conversation-groups", json={"name": "Sales"}, headers=headers())
    assert group.status_code == 201
    group_id = group.json()["id"]

    patched = client.patch(f"/conversations/{mine}", json={"title": "Renamed", "pinned": True, "group_id": group_id}, headers=headers())

    assert patched.status_code == 200
    assert {key: patched.json()[key] for key in ("title", "pinned", "group_id")} == {"title": "Renamed", "pinned": True, "group_id": group_id}
    assert client.patch(f"/conversations/{mine}", json={"title": ""}, headers=headers()).status_code == 422
    assert client.patch(f"/conversation-groups/{group_id}", json={"name": "Sales 2025"}, headers=headers()).json()["name"] == "Sales 2025"
    assert client.get("/conversation-groups", headers=headers()).json() == [{"id": group_id, "name": "Sales 2025"}]
    assert client.delete(f"/conversation-groups/{group_id}", headers=headers()).status_code == 204
    assert client.get("/conversations", headers=headers()).json()[0]["group_id"] is None
    assert client.delete(f"/conversations/{mine}", headers=headers()).status_code == 204
    assert client.get("/conversations", headers=headers()).json() == []
    assert client.get(f"/conversations/{mine}", headers=headers()).status_code == 404


@pytest.mark.parametrize(("method", "path", "body"), [
    ("get", "/conversations/{conversation}", None),
    ("patch", "/conversations/{conversation}", {"title": "Mine now"}),
    ("delete", "/conversations/{conversation}", None),
    ("patch", "/conversation-groups/{group}", {"name": "Mine now"}),
    ("delete", "/conversation-groups/{group}", None),
    ("patch", "/conversations/{own}", {"group_id": "{group}"}),
])
def test_another_users_conversation_or_group_is_not_found(client, store, method, path, body):
    theirs = asked(store, user="lab.analyst")
    their_group = store.create_group("lab.analyst", "Theirs").id
    own = asked(store)
    fill = {"conversation": theirs, "group": their_group, "own": own}
    body = {key: value.format(**fill) for key, value in body.items()} if body else None

    response = client.request(method.upper(), path.format(**fill), json=body, headers=headers())

    assert response.status_code == 404
    assert client.get("/conversations", headers=headers()).json()[0]["id"] == own
    assert store.thread("lab.analyst", theirs).conversation.title == "Doanh thu quý 1"


def test_every_conversation_endpoint_needs_a_session(client):
    for method, path in [("get", "/conversations"), ("get", "/conversations/search?q=x"), ("get", "/conversation-groups")]:
        assert client.request(method.upper(), path).status_code == 401


def test_an_unreachable_store_is_503(client):
    app.dependency_overrides[runtime.get_conversation_store] = lambda: ConversationStore(FakeConversationClient(fail=True))

    assert client.get("/conversations", headers=headers()).status_code == 503


# edit and retry on /ask

@pytest.mark.parametrize("body", [
    {"question": "q", "edit_of_turn": 1},
    {"question": "q", "conversation_id": "c", "edit_of_turn": 1, "retry_of_turn": 1},
    {"question": "q", "conversation_id": "c", "retry_of_turn": 0},
])
def test_an_edit_or_retry_needs_a_conversation_and_one_turn(body):
    with pytest.raises(ValidationError):
        AskRequest.model_validate(body)


def test_an_edit_answers_the_new_question_and_drops_the_turns_after_it(store):
    first = ask_with(answer(), store, {})[0]
    conversation_id = first.headers["x-conversation-id"]
    ask_with(answer(), store, {"conversation_id": conversation_id})
    editor = answer()

    [edited] = ask_with(editor, store, {"question": "Top widgets in Q2 2025", "conversation_id": conversation_id, "edit_of_turn": 1})

    assert kinds(parse(edited.text))[-1] == "done"
    assert editor.histories == [[]]
    thread = store.thread("lab.viewer", conversation_id)
    assert [(turn.turn, turn.revision, turn.question) for turn in thread.turns] == [(1, 2, "Top widgets in Q2 2025")]
    assert [event.event for event in thread.turns[0].events] == ["sql", "result", "chart_spec", "summary", "done"]


def test_a_retry_asks_the_stored_question_again(store):
    first = ask_with(answer(), store, {})[0]
    conversation_id = first.headers["x-conversation-id"]

    ask_with(answer(), store, {"question": "anything", "conversation_id": conversation_id, "retry_of_turn": 1})

    thread = store.thread("lab.viewer", conversation_id)
    assert [(turn.turn, turn.revision, turn.question) for turn in thread.turns] == [(1, 2, QUESTION)]


def test_an_edit_of_a_turn_outside_the_thread_is_404_before_any_llm_call(store):
    first = ask_with(answer(), store, {})[0]
    agent = answer()

    [response] = ask_with(agent, store, {"conversation_id": first.headers["x-conversation-id"], "edit_of_turn": 5})

    assert response.status_code == 404 and agent.started == []


def test_the_patch_contract_tells_a_cleared_group_from_an_untouched_one():
    assert ConversationPatch.model_validate({"group_id": None}).model_fields_set == {"group_id"}
    assert ConversationPatch.model_validate({"title": "x"}).model_fields_set == {"title"}
    assert FakeAgent  # the shared /ask fakes run these edit and retry tests
