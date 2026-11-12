"""Conversations as the web app's sidebar and thread view read them (DECISIONS §15).

A thread turn carries its answer as the stream events the client rendered when
it was asked, so a conversation opened later looks the same.
"""

from datetime import datetime

from pydantic import Field

from app.contracts.events import Event
from app.contracts.query_spec import ContractModel

TITLE_LENGTH = 80


class Conversation(ContractModel):
    id: str
    title: str
    pinned: bool
    group_id: str | None
    # The latest change of the conversation or its newest message.
    updated_at: datetime


class ConversationGroup(ContractModel):
    id: str
    name: str


class ConversationTurn(ContractModel):
    turn: int
    revision: int
    question: str
    # The answer's events in stream order, without status events; empty while the question was never answered.
    events: list[Event]


class ConversationThread(ContractModel):
    conversation: Conversation
    turns: list[ConversationTurn]


class ConversationPatch(ContractModel):
    """The fields a request changes; ``group_id: null`` takes the conversation out of its group."""

    title: str | None = Field(default=None, min_length=1, max_length=TITLE_LENGTH)
    pinned: bool | None = None
    group_id: str | None = None


class GroupInput(ContractModel):
    name: str = Field(min_length=1, max_length=TITLE_LENGTH)
