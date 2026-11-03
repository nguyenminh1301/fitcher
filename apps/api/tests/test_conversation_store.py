"""The conversation store over in-memory conversation tables (DECISIONS §10, §15)."""

from datetime import datetime, timedelta, UTC
import uuid

from fakes import FakeConversationClient
import pytest
from test_contracts import spec

from app.contracts.query_spec import QuerySpec
from app.contracts.result import ColumnInfo, Result
from app.conversation.store import ConversationNotFound, ConversationStore, current_thread
from app.observability.events import ChatMessageRecord

START = datetime(2026, 11, 3, 8, 0, tzinfo=UTC)
RESULT = Result(columns=[ColumnInfo(name="widget_name", type="string", role="dimension")], rows=[["Blue"]], row_count=1)


class Clock:
    def __init__(self):
        self.now = START

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


@pytest.fixture
def client():
    return FakeConversationClient()


@pytest.fixture
def store(client):
    return ConversationStore(client, clock=Clock())


def message(turn: int, revision: int, role: str, content: str = "", seconds: int = 0) -> ChatMessageRecord:
    return ChatMessageRecord(
        user_id="ana", ts=START + timedelta(seconds=seconds), conversation_id="c1", trace_id=f"t{turn}.{revision}",
        role=role, content=content or f"{role} {turn}.{revision}", query_spec="", turn=turn, revision=revision, result="",
    )


def test_first_turn_creates_a_conversation_titled_by_the_question(store, client):
    question = "Which widgets sold best in every region during the first quarter of 2025, and by how much? " * 2

    turn = store.open_turn("ana", None, question)

    assert uuid.UUID(turn.conversation_id).version == 4
    assert (turn.turn, turn.revision, turn.history) == (1, 1, [])
    [conversation] = client.tables["conversations"]
    assert (conversation["user_id"], conversation["conversation_id"]) == ("ana", turn.conversation_id)
    assert conversation["title"] == question[:80]
    assert (conversation["pinned"], conversation["group_id"], conversation["deleted"]) == (False, "", False)
    [asked] = client.tables["chat_messages"]
    assert (asked["role"], asked["content"], asked["turn"], asked["revision"]) == ("user", question, 1, 1)


def test_answer_writes_the_assistant_row_with_spec_and_result_json(store, client):
    turn = store.open_turn("ana", None, "Top widgets in Q1 2025")

    store.answer(turn, trace_id="t1", content="Blue led.", query_spec=spec(), result=RESULT)

    answer = client.tables["chat_messages"][-1]
    assert (answer["role"], answer["content"], answer["trace_id"], answer["turn"], answer["revision"]) == (
        "assistant", "Blue led.", "t1", 1, 1,
    )
    assert QuerySpec.model_validate_json(answer["query_spec"]) == spec()
    assert Result.model_validate_json(answer["result"]) == RESULT


def test_follow_up_continues_the_thread_with_the_next_turn(store, client):
    first = store.open_turn("ana", None, "Top widgets in Q1 2025")
    store.answer(first, trace_id="t1", content="Blue led.", query_spec=spec(), result=RESULT)

    second = store.open_turn("ana", first.conversation_id, "What about last year?")

    assert (second.conversation_id, second.turn, second.revision) == (first.conversation_id, 2, 1)
    [previous] = second.history
    assert (previous.turn, previous.question, previous.answer, previous.trace_id) == (
        1, "Top widgets in Q1 2025", "Blue led.", "t1",
    )
    assert (previous.query_spec, previous.result) == (spec(), RESULT)
    assert len(client.tables["conversations"]) == 1


def test_a_foreign_conversation_is_not_found(store, client):
    mine = store.open_turn("ana", None, "Top widgets")

    with pytest.raises(ConversationNotFound):
        store.open_turn("bao", mine.conversation_id, "Show me the other answer")
    assert [row["user_id"] for row in client.tables["chat_messages"]] == ["ana"]


def test_an_unknown_conversation_is_not_found(store):
    with pytest.raises(ConversationNotFound):
        store.open_turn("ana", str(uuid.uuid4()), "Top widgets")


def test_a_deleted_conversation_is_not_found(store, client):
    turn = store.open_turn("ana", None, "Top widgets")
    row = client.tables["conversations"][0]
    client.tables["conversations"].append({**row, "deleted": True, "updated_at": START + timedelta(days=1)})

    with pytest.raises(ConversationNotFound):
        store.open_turn("ana", turn.conversation_id, "And now?")


def test_a_turn_without_an_answer_keeps_its_place(store):
    first = store.open_turn("ana", None, "Top widgets")

    second = store.open_turn("ana", first.conversation_id, "Top widgets again")

    assert second.turn == 2
    assert [(turn.question, turn.answer, turn.query_spec, turn.result) for turn in second.history] == [
        ("Top widgets", "", None, None),
    ]


def test_current_thread_drops_turns_replaced_by_an_edit():
    rows = [
        message(1, 1, "user"), message(1, 1, "assistant", seconds=1),
        message(2, 1, "user", seconds=2), message(2, 1, "assistant", seconds=3),
        message(1, 2, "user", "edited", seconds=4), message(1, 2, "assistant", "edited answer", seconds=5),
    ]

    thread = current_thread(rows)

    assert [(turn.turn, turn.revision, turn.question, turn.answer) for turn in thread] == [(1, 2, "edited", "edited answer")]


def test_current_thread_keeps_turns_asked_after_an_edit():
    rows = [
        message(1, 1, "user"), message(2, 1, "user", seconds=1), message(1, 2, "user", seconds=2),
        message(2, 2, "user", "asked after the edit", seconds=3),
    ]

    assert [(turn.turn, turn.revision) for turn in current_thread(rows)] == [(1, 2), (2, 2)]


def test_a_new_turn_takes_the_threads_highest_revision(store, client):
    first = store.open_turn("ana", None, "Top widgets")
    edited = message(1, 2, "user", "edited", seconds=10).model_copy(update={"conversation_id": first.conversation_id})
    client.tables["chat_messages"].append(edited.model_dump())

    second = store.open_turn("ana", first.conversation_id, "Next")

    assert (second.turn, second.revision) == (2, 2)
