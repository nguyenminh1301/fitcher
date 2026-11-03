"""The ``/ask`` request and the server-sent events that answer it (DECISIONS §6).

Each event is one SSE frame, ``event: <name>`` with the model as JSON ``data``,
and carries the run's ``trace_id``. Per branch the non-status events are:

- clarify: ``clarify -> done``
- deny: ``deny -> done``
- data success: ``sql -> result -> chart_spec -> summary -> done``
- failure: ``[sql] -> error``

``status`` events come before and between them, one at the start and one at
the end of each graph node. ``sql`` is the checked query that runs, sent when
the guard ends; a repaired query repeats it. ``error`` is always last and
nothing follows ``done``. Events always carry every field, so their JSON
Schema marks fields with defaults as required.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel

from app.contracts.chart_spec import ChartSpec
from app.contracts.query_spec import ContractModel
from app.contracts.result import Result


class AskRequest(ContractModel):
    question: str = Field(min_length=1, max_length=4000)
    # Accepted now; follow-up questions read the conversation from Phase 8.
    conversation_id: str | None = None
    # The browser's IANA time zone; UTC when null (DECISIONS §6 step 5).
    timezone: str | None = None


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
    StatusEvent | ClarifyEvent | DenyEvent | SqlEvent | ResultEvent | ChartSpecEvent | SummaryEvent | DoneEvent | ErrorEvent,
    Field(discriminator="event"),
]


class AskEvent(RootModel[Event]):
    """Any one event of the stream; its JSON Schema is the discriminated union the web app parses."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)
