"""Conversations and their turns in ``agent_logs`` (DECISIONS §10, §15).

Every read and write names the requesting user, so a conversation id that
belongs to another user, or that its owner deleted, is not found. The api
opens a turn before the graph runs: a first question creates the
conversation, titled by the question cut to 80 characters; a follow-up checks
ownership and reads the current thread. The question is written then and the
answer when the run finishes, synchronously, so the next question of the
conversation always reads the previous answer.

The current thread holds, for each turn, its latest revision, and stops before
a turn whose latest revision is older than the latest revision of an earlier
turn: an edit or retry of a turn writes it under a higher revision, which
leaves the turns after it out. A new turn takes the thread's highest revision.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from itertools import groupby
import os
from uuid import uuid4

import clickhouse_connect
from pydantic import BaseModel, ConfigDict

from app.contracts.query_spec import QuerySpec
from app.contracts.result import Result
from app.observability.events import ChatMessageRecord, ConversationRecord, LogRecord, utc_now

DATABASE = "agent_logs"
TITLE_LENGTH = 80
USER = "agent_conversations"

_OWNED = (
    "SELECT count() FROM agent_logs.conversations FINAL "
    "WHERE user_id = {user_id:String} AND conversation_id = {conversation_id:String} AND NOT deleted"
)
_MESSAGES = (
    "SELECT turn, revision, role, content, query_spec, result, trace_id, ts FROM agent_logs.chat_messages "
    "WHERE user_id = {user_id:String} AND conversation_id = {conversation_id:String} ORDER BY turn, revision, ts"
)


class ConversationNotFound(Exception):
    """The conversation does not exist for the requesting user."""


class Turn(BaseModel):
    """One question of the current thread with its answer; the answer is empty when the run never finished."""

    model_config = ConfigDict(frozen=True)

    turn: int
    revision: int
    question: str
    answer: str = ""
    query_spec: QuerySpec | None = None
    result: Result | None = None
    trace_id: str = ""


@dataclass(frozen=True)
class OpenTurn:
    """The turn a question opened, with the thread before it."""

    user_id: str
    conversation_id: str
    turn: int
    revision: int
    history: list[Turn]


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
            trace_id=answer.trace_id if answer else "",
        ))
    return thread


class ConversationStore:
    def __init__(self, client, clock: Callable[[], datetime] = utc_now, new_id: Callable[[], str] = lambda: str(uuid4())):
        self._client = client
        self._clock = clock
        self._new_id = new_id

    def open_turn(self, user_id: str, conversation_id: str | None, question: str) -> OpenTurn:
        """Open the next turn of ``conversation_id``, or of a new conversation when it is None, and write the question.

        Raises ``ConversationNotFound`` when ``user_id`` has no such conversation.
        """
        if conversation_id is None:
            conversation_id, history = self._new_id(), []
            now = self._clock()
            self._insert(ConversationRecord(
                user_id=user_id, conversation_id=conversation_id, title=question[:TITLE_LENGTH], pinned=False,
                group_id="", deleted=False, created_at=now, updated_at=now,
            ))
        else:
            history = self._thread(user_id, conversation_id)
        turn = OpenTurn(
            user_id=user_id, conversation_id=conversation_id, turn=history[-1].turn + 1 if history else 1,
            revision=max((item.revision for item in history), default=1), history=history,
        )
        self._write(turn, role="user", content=question, trace_id="")
        return turn

    def answer(
        self, turn: OpenTurn, *, trace_id: str, content: str, query_spec: QuerySpec | None, result: Result | None,
    ) -> None:
        self._write(
            turn, role="assistant", content=content, trace_id=trace_id,
            query_spec=query_spec.model_dump_json() if query_spec else "", result=result.model_dump_json() if result else "",
        )

    def _thread(self, user_id: str, conversation_id: str) -> list[Turn]:
        parameters = {"user_id": user_id, "conversation_id": conversation_id}
        if not self._client.query(_OWNED, parameters=parameters).result_rows[0][0]:
            raise ConversationNotFound(conversation_id)
        rows = self._client.query(_MESSAGES, parameters=parameters).result_rows
        return current_thread([
            ChatMessageRecord(
                user_id=user_id, conversation_id=conversation_id, turn=turn, revision=revision, role=role,
                content=content, query_spec=query_spec, result=result, trace_id=trace_id, ts=ts,
            )
            for turn, revision, role, content, query_spec, result, trace_id, ts in rows
        ])

    def _write(self, turn: OpenTurn, *, role: str, content: str, trace_id: str, query_spec: str = "", result: str = "") -> None:
        self._insert(ChatMessageRecord(
            user_id=turn.user_id, ts=self._clock(), conversation_id=turn.conversation_id, trace_id=trace_id, role=role,
            content=content, query_spec=query_spec, turn=turn.turn, revision=turn.revision, result=result,
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
