"""The ``/ask`` request and the server-sent events that answer it (DECISIONS §6).

Each event is one SSE frame, ``event: <name>`` with the model as JSON ``data``,
and carries the run's ``trace_id``. Per branch the non-status events are:

- clarify: ``clarify -> done``
- deny: ``deny -> done``
- data success: ``sql -> result -> chart_spec -> summary -> done``
- failure: ``[sql] -> error``
- out_of_scope and metadata_qa: ``summary -> done``
- chart_edit: ``result -> chart_spec -> done``, the previous turn's result sent again
- blocked: ``blocked -> done``, when screening stops the question or is unavailable, or the
  LLM gateway rejects a request (DECISIONS §9); the message never repeats the question

``status`` events come before and between them, one at the start and one at
the end of each graph node. ``sql`` is the checked query that runs, sent when
the guard ends; a repaired query repeats it. ``error`` is always last and
nothing follows ``done``. Events always carry every field, so their JSON
Schema marks fields with defaults as required.
"""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, RootModel, model_validator

from app.contracts.chart_spec import ChartSpec
from app.contracts.query_spec import ContractModel
from app.contracts.result import Result


class AskRequest(ContractModel):
    question: str = Field(min_length=1, max_length=4000)
    # A conversation of the asking user to continue; null starts one. The response names it in X-Conversation-Id.
    conversation_id: str | None = None
    # The browser's IANA time zone; UTC when null (DECISIONS §6 step 5).
    timezone: str | None = None
    # Ask this question in place of that turn of the conversation, under a new revision; later turns leave the thread.
    edit_of_turn: int | None = Field(default=None, ge=1)
    # Ask that turn's stored question again under a new revision; ``question`` is not used.
    retry_of_turn: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _one_turn_of_a_conversation(self) -> Self:
        if self.edit_of_turn is not None and self.retry_of_turn is not None:
            raise ValueError("set edit_of_turn or retry_of_turn, not both")
        if (self.edit_of_turn is not None or self.retry_of_turn is not None) and self.conversation_id is None:
            raise ValueError("an edit or retry needs the conversation_id it belongs to")
        return self


class EventModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, json_schema_serialization_defaults_required=True)

    trace_id: str


class StatusEvent(EventModel):
    event: Literal["status"] = "status"
    node: str
    phase: Literal["start", "end"]
    # The SQL generation this node belongs to, from 1; set on generate_sql only.
    attempt: int | None = None


class ClarifyOption(ContractModel):
    id: str
    label: str


class ClarifyEvent(EventModel):
    event: Literal["clarify"] = "clarify"
    question: str
    options: list[ClarifyOption] = []
    lang: str


class DenyEvent(EventModel):
    event: Literal["deny"] = "deny"
    message: str
    role: str
    # The dataset, or dataset.column / dataset.metric items, the role may not read.
    blocked: list[str]
    lang: str


class BlockedEvent(EventModel):
    event: Literal["blocked"] = "blocked"
    message: str
    lang: str


class SqlEvent(EventModel):
    event: Literal["sql"] = "sql"
    sql: str
    attempt: int = Field(ge=1)


class ResultEvent(EventModel):
    event: Literal["result"] = "result"
    result: Result


class ChartSpecEvent(EventModel):
    event: Literal["chart_spec"] = "chart_spec"
    spec: ChartSpec


class SummaryEvent(EventModel):
    event: Literal["summary"] = "summary"
    text: str
    lang: str
    warnings: list[str] = []


class DoneEvent(EventModel):
    event: Literal["done"] = "done"


class ErrorEvent(EventModel):
    """``failed``: no SQL attempt produced a result; ``internal``: the run broke, with no detail for the client."""

    event: Literal["error"] = "error"
    kind: Literal["failed", "internal"]
    message: str
    # The last SQL attempt and its error, for a failed run.
    sql: str | None = None
    error: str | None = None


Event = Annotated[
    StatusEvent | ClarifyEvent | DenyEvent | BlockedEvent | SqlEvent | ResultEvent | ChartSpecEvent | SummaryEvent
    | DoneEvent | ErrorEvent,
    Field(discriminator="event"),
]


class AskEvent(RootModel[Event]):
    """Any one event of the stream; its JSON Schema is the discriminated union the web app parses."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)
