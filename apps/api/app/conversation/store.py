"""Conversations, their turns and the user's groups in ``agent_logs`` (DECISIONS §10, §15).

Every read and write names the requesting user, so a conversation or group id
that belongs to another user, or that its owner deleted, is not found. The api
opens a turn before the graph runs: a first question creates the
conversation, titled by the question cut to 80 characters; a follow-up checks
ownership and reads the current thread. The question is written then and the
answer when the run finishes, synchronously, so the next question of the
conversation always reads the previous answer. An answer keeps its stream
events (without status events and without the result, whose rows are stored
once in ``result``), so a thread opened later renders as it did.

The current thread holds, for each turn, its latest revision, and stops before
a turn whose latest revision is older than the latest revision of an earlier
turn. A new turn takes the thread's highest revision. An edit or retry of turn
k writes it under the conversation's highest revision plus one, which leaves
the turns after it out of the thread and of the context.

Conversations and groups change by new ``ReplacingMergeTree`` rows read with
``FINAL``; each new row's ``updated_at`` is after the previous one, so two
changes within one millisecond keep their order. Delete only hides: the rows
stay until the 90-day TTL. Search folds case and diacritics over the user's
titles and own questions, read by the ``(user_id, ...)`` key.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import groupby
import json
import os
from uuid import uuid4

import clickhouse_connect
from pydantic import BaseModel, ConfigDict, TypeAdapter

from app.contracts.chart_spec import table_spec
from app.contracts.conversations import (
    TITLE_LENGTH, Conversation, ConversationGroup, ConversationPatch, ConversationThread, ConversationTurn,
)
from app.contracts.events import ChartSpecEvent, DoneEvent, Event, EventModel, ResultEvent, SummaryEvent
from app.contracts.query_spec import QuerySpec
from app.contracts.result import Result
from app.observability.events import ChatMessageRecord, ConversationGroupRecord, ConversationRecord, LogRecord, utc_now
from app.text import fold

DATABASE = "agent_logs"
USER = "agent_conversations"
# Stream events kept apart from an answer's stored events.
NOT_STORED = frozenset({"status", "result"})

CONVERSATION_COLUMNS = ("conversation_id", "title", "pinned", "group_id", "deleted", "created_at", "updated_at")
GROUP_COLUMNS = ("group_id", "name", "deleted", "updated_at")
MESSAGE_COLUMNS = ("turn", "revision", "role", "content", "query_spec", "result", "trace_id", "ts", "events")

CONVERSATIONS_SQL = (
    f"SELECT {', '.join(CONVERSATION_COLUMNS)} FROM agent_logs.conversations FINAL WHERE user_id = {{user_id:String}}"
)
CONVERSATION_SQL = f"{CONVERSATIONS_SQL} AND conversation_id = {{conversation_id:String}}"
GROUPS_SQL = (
    f"SELECT {', '.join(GROUP_COLUMNS)} FROM agent_logs.conversation_groups FINAL WHERE user_id = {{user_id:String}}"
)
GROUP_SQL = f"{GROUPS_SQL} AND group_id = {{group_id:String}}"
MESSAGES_SQL = (
    f"SELECT {', '.join(MESSAGE_COLUMNS)} FROM agent_logs.chat_messages "
    "WHERE user_id = {user_id:String} AND conversation_id = {conversation_id:String} ORDER BY turn, revision, ts"
)
ACTIVITY_SQL = (
    "SELECT conversation_id, max(ts) FROM agent_logs.chat_messages WHERE user_id = {user_id:String} GROUP BY conversation_id"
)
QUESTIONS_SQL = (
    "SELECT conversation_id, content FROM agent_logs.chat_messages WHERE user_id = {user_id:String} AND role = 'user'"
)

_EVENTS = TypeAdapter(list[Event])


class ConversationNotFound(Exception):
    """The conversation does not exist for the requesting user."""


class GroupNotFound(Exception):
    """The group does not exist for the requesting user."""


class TurnNotFound(Exception):
    """The turn to edit or retry is not in the conversation's current thread."""


class Turn(BaseModel):
    """One question of the current thread with its answer; ``answered`` is false while the run never finished."""

    model_config = ConfigDict(frozen=True)

    turn: int
    revision: int
    question: str
    answer: str = ""
    query_spec: QuerySpec | None = None
    result: Result | None = None
    trace_id: str = ""
    answered: bool = False
    # The answer's stored events as JSON; empty for an answer stored before events were kept.
    events: str = ""


@dataclass(frozen=True)
class OpenTurn:
    """The turn a question opened, with the thread before it and the question the run answers."""

    user_id: str
    conversation_id: str
    turn: int
    revision: int
    history: list[Turn]
    question: str = ""


def current_thread(rows: list[ChatMessageRecord]) -> list[Turn]:
    """The turns of ``rows`` that are still in the conversation, in order."""
    thread: list[Turn] = []
    highest = 0
    ordered = sorted(rows, key=lambda row: (row.turn, row.revision, row.ts))
    for number, messages in groupby(ordered, key=lambda row: row.turn):
        messages = list(messages)
        revision = messages[-1].revision
        if revision < highest:
            break
        highest = revision
        latest = {row.role: row for row in messages if row.revision == revision}
        question, answer = latest.get("user"), latest.get("assistant")
        thread.append(Turn(
            turn=number, revision=revision, question=question.content if question else "",
            answer=answer.content if answer else "",
            query_spec=QuerySpec.model_validate_json(answer.query_spec) if answer and answer.query_spec else None,
            result=Result.model_validate_json(answer.result) if answer and answer.result else None,
            trace_id=answer.trace_id if answer else "", answered=answer is not None,
            events=answer.events if answer else "",
        ))
    return thread


def shown_events(turn: Turn) -> list[EventModel]:
    """The answer's events as streamed, with the stored result put back before its chart spec."""
    if not turn.answered:
        return []
    trace = {"trace_id": turn.trace_id}
    if turn.events:
        events = list(_EVENTS.validate_json(turn.events))
        if turn.result is not None:
            at = next((index for index, event in enumerate(events) if event.event == "chart_spec"), len(events))
            events.insert(at, ResultEvent(**trace, result=turn.result))
        return events
    events: list[EventModel] = []
    if turn.result is not None:
        events += [ResultEvent(**trace, result=turn.result), ChartSpecEvent(**trace, spec=table_spec(turn.result))]
    if turn.answer:
        events.append(SummaryEvent(**trace, text=turn.answer, lang="en"))
    return [*events, DoneEvent(**trace)]


class ConversationStore:
    def __init__(
        self, client, clock: Callable[[], datetime] = utc_now, new_id: Callable[[], str] = lambda: str(uuid4()),
    ):
        self._client = client
        self._clock = clock
        self._new_id = new_id

    # turns

    def open_turn(
        self, user_id: str, conversation_id: str | None, question: str, *,
        edit_of_turn: int | None = None, retry_of_turn: int | None = None,
    ) -> OpenTurn:
        """Open the next turn, or a new revision of an earlier one, and write the question.

        ``conversation_id`` None starts a conversation. Raises ``ConversationNotFound`` when ``user_id``
        has no such conversation and ``TurnNotFound`` when the edited or retried turn is not in its thread.
        """
        if conversation_id is None:
            conversation_id, history, revision, number = self._new_id(), [], 1, 1
            now = self._clock()
            self._insert(ConversationRecord(
                user_id=user_id, conversation_id=conversation_id, title=question[:TITLE_LENGTH], pinned=False,
                group_id="", deleted=False, created_at=now, updated_at=now,
            ))
        else:
            self._owned(user_id, conversation_id)
            rows = self._messages(user_id, conversation_id)
            thread = current_thread(rows)
            replaced = edit_of_turn or retry_of_turn
            if replaced is None:
                history, number = thread, thread[-1].turn + 1 if thread else 1
                revision = max((item.revision for item in thread), default=1)
            else:
                target = next((item for item in thread if item.turn == replaced), None)
                if target is None:
                    raise TurnNotFound(replaced)
                history, number = [item for item in thread if item.turn < replaced], replaced
                revision = max(row.revision for row in rows) + 1
                if retry_of_turn is not None:
                    question = target.question
        turn = OpenTurn(user_id, conversation_id, number, revision, history, question)
        self._write(turn, role="user", content=question, trace_id="")
        return turn

    def answer(
        self, turn: OpenTurn, *, trace_id: str, content: str, query_spec: QuerySpec | None, result: Result | None,
        events: Sequence[EventModel] = (),
    ) -> None:
        kept = [event.model_dump(mode="json") for event in events if event.event not in NOT_STORED]
        self._write(
            turn, role="assistant", content=content, trace_id=trace_id,
            query_spec=query_spec.model_dump_json() if query_spec else "", result=result.model_dump_json() if result else "",
            events=json.dumps(kept, ensure_ascii=False) if kept else "",
        )

    def thread(self, user_id: str, conversation_id: str) -> ConversationThread:
        row = self._owned(user_id, conversation_id)
        turns = current_thread(self._messages(user_id, conversation_id))
        return ConversationThread(
            conversation=self._view(row, self._activity(user_id).get(conversation_id)),
            turns=[
                ConversationTurn(turn=turn.turn, revision=turn.revision, question=turn.question, events=shown_events(turn))
                for turn in turns
            ],
        )

    # the sidebar

    def conversations(self, user_id: str, *, limit: int, offset: int) -> list[Conversation]:
        return self._newest(user_id)[offset:offset + limit]

    def search(self, user_id: str, query: str) -> list[Conversation]:
        wanted = fold(query)
        asked: dict[str, list[str]] = {}
        for conversation_id, content in self._query(QUESTIONS_SQL, user_id=user_id):
            asked.setdefault(conversation_id, []).append(fold(content))
        return [
            item for item in self._newest(user_id)
            if wanted in fold(item.title) or any(wanted in question for question in asked.get(item.id, []))
        ]

    def update(self, user_id: str, conversation_id: str, patch: ConversationPatch) -> Conversation:
        row = self._owned(user_id, conversation_id)
        changed = patch.model_dump(include=patch.model_fields_set)
        if changed.get("group_id") is not None:
            self._group(user_id, changed["group_id"])
        if "group_id" in changed:
            changed["group_id"] = changed["group_id"] or ""
        if changed.get("pinned") is None:
            changed.pop("pinned", None)
        if changed.get("title") is None:
            changed.pop("title", None)
        updated = row.model_copy(update={**changed, "updated_at": self._after(row.updated_at)})
        self._insert(updated)
        return self._view(updated, self._activity(user_id).get(conversation_id))

    def delete(self, user_id: str, conversation_id: str) -> None:
        row = self._owned(user_id, conversation_id)
        self._insert(row.model_copy(update={"deleted": True, "updated_at": self._after(row.updated_at)}))

    # groups

    def groups(self, user_id: str) -> list[ConversationGroup]:
        rows = [
            ConversationGroupRecord(user_id=user_id, **dict(zip(GROUP_COLUMNS, values)))
            for values in self._query(GROUPS_SQL, user_id=user_id)
        ]
        return [
            ConversationGroup(id=row.group_id, name=row.name)
            for row in sorted(rows, key=lambda row: row.name) if not row.deleted
        ]

    def create_group(self, user_id: str, name: str) -> ConversationGroup:
        record = ConversationGroupRecord(
            user_id=user_id, group_id=self._new_id(), name=name, deleted=False, updated_at=self._clock(),
        )
        self._insert(record)
        return ConversationGroup(id=record.group_id, name=name)

    def rename_group(self, user_id: str, group_id: str, name: str) -> ConversationGroup:
        row = self._group(user_id, group_id)
        self._insert(row.model_copy(update={"name": name, "updated_at": self._after(row.updated_at)}))
        return ConversationGroup(id=group_id, name=name)

    def delete_group(self, user_id: str, group_id: str) -> None:
        """Hide the group and move its conversations back to no group."""
        row = self._group(user_id, group_id)
        self._insert(row.model_copy(update={"deleted": True, "updated_at": self._after(row.updated_at)}))
        for conversation in self._rows(user_id):
            if conversation.group_id == group_id and not conversation.deleted:
                ungrouped = {"group_id": "", "updated_at": self._after(conversation.updated_at)}
                self._insert(conversation.model_copy(update=ungrouped))

    # reads

    def _query(self, sql: str, **parameters: str) -> list[tuple]:
        return self._client.query(sql, parameters=parameters).result_rows

    def _rows(self, user_id: str) -> list[ConversationRecord]:
        return [
            ConversationRecord(user_id=user_id, **dict(zip(CONVERSATION_COLUMNS, values)))
            for values in self._query(CONVERSATIONS_SQL, user_id=user_id)
        ]

    def _owned(self, user_id: str, conversation_id: str) -> ConversationRecord:
        rows = self._query(CONVERSATION_SQL, user_id=user_id, conversation_id=conversation_id)
        row = ConversationRecord(user_id=user_id, **dict(zip(CONVERSATION_COLUMNS, rows[0]))) if rows else None
        if row is None or row.deleted:
            raise ConversationNotFound(conversation_id)
        return row

    def _group(self, user_id: str, group_id: str) -> ConversationGroupRecord:
        rows = self._query(GROUP_SQL, user_id=user_id, group_id=group_id)
        row = ConversationGroupRecord(user_id=user_id, **dict(zip(GROUP_COLUMNS, rows[0]))) if rows else None
        if row is None or row.deleted:
            raise GroupNotFound(group_id)
        return row

    def _messages(self, user_id: str, conversation_id: str) -> list[ChatMessageRecord]:
        return [
            ChatMessageRecord(user_id=user_id, conversation_id=conversation_id, **dict(zip(MESSAGE_COLUMNS, values)))
            for values in self._query(MESSAGES_SQL, user_id=user_id, conversation_id=conversation_id)
        ]

    def _activity(self, user_id: str) -> dict[str, datetime]:
        return dict(self._query(ACTIVITY_SQL, user_id=user_id))

    def _newest(self, user_id: str) -> list[Conversation]:
        activity = self._activity(user_id)
        shown = [self._view(row, activity.get(row.conversation_id)) for row in self._rows(user_id) if not row.deleted]
        return sorted(shown, key=lambda item: item.updated_at, reverse=True)

    @staticmethod
    def _view(row: ConversationRecord, last_message: datetime | None) -> Conversation:
        updated = max(row.updated_at, last_message) if last_message else row.updated_at
        return Conversation(
            id=row.conversation_id, title=row.title, pinned=row.pinned, group_id=row.group_id or None, updated_at=updated,
        )

    # writes

    def _after(self, previous: datetime) -> datetime:
        return max(self._clock(), previous + timedelta(milliseconds=1))

    def _write(
        self, turn: OpenTurn, *, role: str, content: str, trace_id: str, query_spec: str = "", result: str = "",
        events: str = "",
    ) -> None:
        self._insert(ChatMessageRecord(
            user_id=turn.user_id, ts=self._clock(), conversation_id=turn.conversation_id, trace_id=trace_id, role=role,
            content=content, query_spec=query_spec, turn=turn.turn, revision=turn.revision, result=result, events=events,
        ))

    def _insert(self, record: LogRecord) -> None:
        row = record.model_dump()
        self._client.insert(record.TABLE, [list(row.values())], column_names=list(row), database=DATABASE)


def conversations_client(env: Mapping[str, str] | None = None):
    env = os.environ if env is None else env
    password = env.get("CLICKHOUSE_CONVERSATIONS_PASSWORD", "")
    if not password:
        raise RuntimeError("CLICKHOUSE_CONVERSATIONS_PASSWORD must be set")
    return clickhouse_connect.get_client(
        host=env.get("CLICKHOUSE_HOST", "clickhouse"),
        port=int(env.get("CLICKHOUSE_HTTP_PORT", "8123")),
        username=USER,
        password=password,
        database=DATABASE,
    )
