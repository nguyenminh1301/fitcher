"""Managing a user's conversations: threads with their answers, edit and retry, list, search, update and groups (§15)."""

from datetime import timedelta

from fakes import FakeConversationClient
import pytest
from test_contracts import spec
from test_conversation_store import RESULT, START, Clock

from app.contracts.events import ChartSpecEvent, ClarifyEvent, ClarifyOption, DoneEvent, ResultEvent, SqlEvent, StatusEvent, SummaryEvent
from app.contracts.chart_spec import table_spec
from app.contracts.conversations import ConversationPatch
from app.conversation.store import ConversationNotFound, ConversationStore, GroupNotFound, TurnNotFound

T = {"trace_id": "t" * 32}


@pytest.fixture
def client():
    return FakeConversationClient()


@pytest.fixture
def store(client):
    return ConversationStore(client, clock=Clock())


def answered(store, user="ana", conversation_id=None, question="Top widgets in Q1 2025", text="Blue led."):
    turn = store.open_turn(user, conversation_id, question)
    events = [
        StatusEvent(**T, node="extract", phase="start"), SqlEvent(**T, sql="SELECT 1", attempt=1),
        ResultEvent(**T, result=RESULT), ChartSpecEvent(**T, spec=table_spec(RESULT)),
        SummaryEvent(**T, text=text, lang="en"), DoneEvent(**T),
    ]
    store.answer(turn, trace_id=T["trace_id"], content=text, query_spec=spec(), result=RESULT, events=events)
    return turn


# threads

def test_a_thread_shows_each_answer_with_its_events_and_the_result_put_back(store, client):
    turn = answered(store)

    thread = store.thread("ana", turn.conversation_id)

    assert (thread.conversation.id, thread.conversation.title) == (turn.conversation_id, "Top widgets in Q1 2025")
    [shown] = thread.turns
    assert (shown.turn, shown.revision, shown.question) == (1, 1, "Top widgets in Q1 2025")
    assert [event.event for event in shown.events] == ["sql", "result", "chart_spec", "summary", "done"]
    assert shown.events[1].result == RESULT
    stored = client.tables["chat_messages"][-1]["events"]
    assert '"status"' not in stored and '"result"' not in stored and "Blue" not in stored.split('"summary"')[0]


def test_a_clarify_keeps_its_options(store):
    turn = store.open_turn("ana", None, "How did we do?")
    options = [ClarifyOption(id="metric:widget_revenue", label="Widget revenue")]
    clarify = ClarifyEvent(**T, question="Which measure should I report?", options=options, lang="en")
    store.answer(turn, trace_id=T["trace_id"], content=clarify.question, query_spec=None, result=None, events=[clarify, DoneEvent(**T)])

    [shown] = store.thread("ana", turn.conversation_id).turns

    assert shown.events[0].options == options


def test_an_answer_stored_without_events_reads_as_its_summary_and_result(store, client):
    turn = store.open_turn("ana", None, "Top widgets")
    store.answer(turn, trace_id=T["trace_id"], content="Blue led.", query_spec=spec(), result=RESULT)

    [shown] = store.thread("ana", turn.conversation_id).turns

    assert [event.event for event in shown.events] == ["result", "chart_spec", "summary", "done"]
    assert shown.events[2].text == "Blue led."


def test_a_question_without_an_answer_shows_no_events(store):
    turn = store.open_turn("ana", None, "Top widgets")

    assert store.thread("ana", turn.conversation_id).turns[0].events == []


def test_another_users_thread_is_not_found(store):
    turn = answered(store)

    with pytest.raises(ConversationNotFound):
        store.thread("bao", turn.conversation_id)


# edit and retry

def three_turns(store) -> str:
    first = answered(store, question="First question")
    answered(store, conversation_id=first.conversation_id, question="Second question")
    answered(store, conversation_id=first.conversation_id, question="Third question")
    return first.conversation_id


def test_editing_turn_one_replaces_the_turns_after_it(store):
    conversation_id = three_turns(store)

    edited = store.open_turn("ana", conversation_id, "First question, edited", edit_of_turn=1)
    store.answer(edited, trace_id=T["trace_id"], content="Edited answer.", query_spec=spec(), result=RESULT)

    assert (edited.turn, edited.revision, edited.history, edited.question) == (1, 2, [], "First question, edited")
    thread = store.thread("ana", conversation_id)
    assert [(turn.turn, turn.revision, turn.question) for turn in thread.turns] == [(1, 2, "First question, edited")]
    follow_up = store.open_turn("ana", conversation_id, "And then?")
    assert [turn.question for turn in follow_up.history] == ["First question, edited"]
    assert (follow_up.turn, follow_up.revision) == (2, 2)


def test_retrying_a_turn_asks_its_stored_question_again(store):
    conversation_id = three_turns(store)

    retried = store.open_turn("ana", conversation_id, "ignored text", retry_of_turn=2)

    assert (retried.turn, retried.revision, retried.question) == (2, 2, "Second question")
    assert [turn.question for turn in retried.history] == ["First question"]


def test_editing_a_turn_that_is_not_in_the_thread_is_not_found(store):
    conversation_id = three_turns(store)

    with pytest.raises(TurnNotFound):
        store.open_turn("ana", conversation_id, "q", edit_of_turn=7)


# list and search

def test_the_list_is_newest_activity_first_with_limit_and_offset(store):
    old = answered(store, question="Old question")
    newer = answered(store, question="Newer question")
    answered(store, conversation_id=old.conversation_id, question="Old question continued")

    listed = store.conversations("ana", limit=10, offset=0)

    assert [item.id for item in listed] == [old.conversation_id, newer.conversation_id]
    assert listed[0].updated_at > listed[1].updated_at
    assert [item.id for item in store.conversations("ana", limit=1, offset=1)] == [newer.conversation_id]
    assert store.conversations("bao", limit=10, offset=0) == []


def test_search_matches_titles_and_own_questions_ignoring_case_and_diacritics(store):
    first = answered(store, question="Doanh thu quý 1")
    second = answered(store, question="Top widgets")
    answered(store, conversation_id=second.conversation_id, question="Còn DOANH THU năm ngoái?")
    answered(store, user="bao", question="doanh thu của Bao")

    found = store.search("ana", "doanh thu")

    assert {item.id for item in found} == {first.conversation_id, second.conversation_id}
    assert store.search("ana", "DOANH THU QUY") == [item for item in found if item.id == first.conversation_id]


# update, delete and groups

def test_rename_pin_and_group_write_a_new_row(store, client):
    turn = answered(store)
    group = store.create_group("ana", "Sales")

    updated = store.update("ana", turn.conversation_id, ConversationPatch(title="Renamed", pinned=True, group_id=group.id))

    assert (updated.title, updated.pinned, updated.group_id) == ("Renamed", True, group.id)
    assert len(client.tables["conversations"]) == 2
    rows = client.tables["conversations"]
    assert rows[1]["updated_at"] > rows[0]["updated_at"]
    cleared = store.update("ana", turn.conversation_id, ConversationPatch(group_id=None))
    assert (cleared.title, cleared.pinned, cleared.group_id) == ("Renamed", True, None)


def test_two_changes_in_one_millisecond_keep_their_order(client):
    frozen = ConversationStore(client, clock=lambda: START)
    turn = frozen.open_turn("ana", None, "q")

    frozen.update("ana", turn.conversation_id, ConversationPatch(title="first"))
    frozen.update("ana", turn.conversation_id, ConversationPatch(title="second"))

    assert frozen.thread("ana", turn.conversation_id).conversation.title == "second"
    assert client.tables["conversations"][-1]["updated_at"] == START + timedelta(milliseconds=2)


def test_a_conversation_cannot_move_into_another_users_group(store):
    turn = answered(store)
    theirs = store.create_group("bao", "Theirs")

    with pytest.raises(GroupNotFound):
        store.update("ana", turn.conversation_id, ConversationPatch(group_id=theirs.id))


def test_a_deleted_conversation_is_gone_for_its_owner_but_its_rows_stay(store, client):
    turn = answered(store, question="Doanh thu")

    store.delete("ana", turn.conversation_id)

    assert store.conversations("ana", limit=10, offset=0) == [] and store.search("ana", "doanh") == []
    with pytest.raises(ConversationNotFound):
        store.thread("ana", turn.conversation_id)
    with pytest.raises(ConversationNotFound):
        store.delete("ana", turn.conversation_id)
    assert len(client.tables["chat_messages"]) == 2 and client.tables["conversations"][-1]["deleted"] is True


def test_groups_are_created_renamed_listed_and_deleted_per_user(store):
    sales = store.create_group("ana", "Sales")
    store.create_group("bao", "Bao's")

    store.rename_group("ana", sales.id, "Sales 2025")

    assert [(group.id, group.name) for group in store.groups("ana")] == [(sales.id, "Sales 2025")]
    with pytest.raises(GroupNotFound):
        store.rename_group("bao", sales.id, "Taken")
    store.delete_group("ana", sales.id)
    assert store.groups("ana") == []
    with pytest.raises(GroupNotFound):
        store.delete_group("ana", sales.id)


def test_deleting_a_group_moves_its_conversations_back_to_no_group(store):
    turn = answered(store)
    group = store.create_group("ana", "Sales")
    store.update("ana", turn.conversation_id, ConversationPatch(group_id=group.id))

    store.delete_group("ana", group.id)

    assert store.conversations("ana", limit=10, offset=0)[0].group_id is None
