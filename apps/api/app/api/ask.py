"""``POST /ask``: answer one question as a stream of server-sent events (DECISIONS §6).

The request is authenticated, mapped to its pack role and rate limited before
the graph starts. The question then opens a turn of its conversation: a new
one when the request names none, otherwise one the user owns, or 404; an edit
or retry opens a new revision of a turn in its thread, or 404. The
conversation id is returned in the ``X-Conversation-Id`` header. The graph
runs in a worker thread over the conversation's thread so far;
``AnswerEvents`` turns each node's start and end, and the final state, into
the events of ``app.contracts.events`` in the fixed order. The question is
written to the conversation once the ``screen`` node lets the run continue,
so a question screening stops is never stored as a turn (DECISIONS §9); the
answer is stored before its last event is sent, so a follow-up can read it
at once.
A comment frame keeps the connection open every 15 seconds. When the client
disconnects, the run stops at its next node and the ClickHouse query it may
be running is killed.
"""

import asyncio
from collections.abc import AsyncIterator, Mapping
import logging
import math
import threading
from typing import Annotated, Literal, Protocol
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.agent.nodes.resolve_time import TimeResolutionError, reference_date
from app.agent.nodes.screen import blocked_message
from app.agent.state import AgentState, RunCancelled
from app.api.agent import Agent, AgentRun
from app.api.auth import current_principal, current_role
from app.api.rate_limit import RateLimiter
from app.api.runtime import get_agent, get_conversation_store, get_rate_limiter, unavailable
from app.auth.principal import Principal
from app.contracts.events import (
    AskRequest, BlockedEvent, ChartSpecEvent, ClarifyEvent, DenyEvent, DoneEvent, ErrorEvent, EventModel, ResultEvent,
    SqlEvent, StatusEvent, SummaryEvent,
)
from app.conversation.store import ConversationNotFound, ConversationStore, OpenTurn, TurnNotFound

logger = logging.getLogger(__name__)
router = APIRouter()

HEARTBEAT_SECONDS = 15.0
INTERNAL_ERROR = "The answer could not be completed because of an internal error."
TERMINAL = frozenset({"done", "error"})


def _language(state: Mapping) -> str:
    return getattr(state.get("extraction"), "language", None) or state.get("language") or "en"


class AnswerEvents:
    """The events of one run, from graph progress and the final state."""

    def __init__(self, role: str):
        self.role = role
        self.trace_id = ""
        # Every event of the answer other than status, in stream order; stored with the answer.
        self.answered: list[EventModel] = []

    def _keep(self, events: list[EventModel]) -> list[EventModel]:
        self.answered += [event for event in events if event.event != "status"]
        return events

    def node(self, name: str, phase: Literal["start", "end"], state: AgentState, update: Mapping | None) -> list[EventModel]:
        self.trace_id = state["trace_id"]
        trace = {"trace_id": self.trace_id}
        attempt = len(state.get("attempts", [])) + 1 if name == "generate_sql" else None
        events: list[EventModel] = [StatusEvent(**trace, node=name, phase=phase, attempt=attempt)]
        if phase == "start" or update is None:
            return events
        if name == "guard":
            # The guarded SQL, with its enforced LIMIT, is the one that runs; a rejected one is shown as generated.
            attempts = update.get("attempts", state["attempts"])
            events.append(SqlEvent(**trace, sql=attempts[-1].sql, attempt=len(attempts)))
        elif name == "shape_result":
            events.append(ResultEvent(**trace, result=update["result"]))
        elif name == "chart_recommender":
            events.append(ChartSpecEvent(**trace, spec=update["chart_spec"]))
        elif name == "chart_edit":
            # The stored result is sent again so the client always holds the rows it draws.
            events += [ResultEvent(**trace, result=update["result"]), ChartSpecEvent(**trace, spec=update["chart_spec"])]
        elif name == "summarize":
            warnings = update.get("warnings", state.get("warnings", []))
            events.append(SummaryEvent(**trace, text=update.get("summary") or "", lang=_language(state), warnings=warnings))
        return self._keep(events)

    def finish(self, state: AgentState) -> list[EventModel]:
        return self._keep(self._closing(state))

    def _closing(self, state: AgentState) -> list[EventModel]:
        self.trace_id = state["trace_id"]
        trace = {"trace_id": self.trace_id}
        if state.get("blocked"):
            lang = state.get("language") or "en"
            return [BlockedEvent(**trace, message=blocked_message(state["blocked"], lang), lang=lang), DoneEvent(**trace)]
        if state.get("reply") is not None:
            return [SummaryEvent(**trace, text=state["reply"], lang=_language(state)), DoneEvent(**trace)]
        if state.get("clarification"):
            asked = state["clarification"]
            return [ClarifyEvent(**trace, question=asked.question, options=asked.options, lang=asked.lang), DoneEvent(**trace)]
        if state.get("rejection"):
            # A question the flow cannot read at all is refused in English, without options.
            return [ClarifyEvent(**trace, question=state["rejection"], lang="en"), DoneEvent(**trace)]
        if state.get("denial"):
            denial = state["denial"]
            deny = DenyEvent(**trace, message=denial.message, role=self.role, blocked=denial.blocked, lang=_language(state))
            return [deny, DoneEvent(**trace)]
        if state.get("result") is not None:
            return [DoneEvent(**trace)]
        attempts = state.get("attempts", [])
        errors = state.get("errors", [])
        error = attempts[-1].error if attempts and attempts[-1].error else (errors[-1] if errors else None)
        return [ErrorEvent(
            **trace, kind="failed", message=error.message if error else "The question could not be answered.",
            sql=(attempts[-1].sql or None) if attempts else None, error=str(error) if error else None,
        )]

    def internal(self) -> list[EventModel]:
        return [ErrorEvent(trace_id=self.trace_id or uuid4().hex, kind="internal", message=INTERNAL_ERROR)]


def frame(event: EventModel) -> str:
    return f"event: {event.event}\ndata: {event.model_dump_json()}\n\n"


class Record(Protocol):
    """Stores a run's turn: the question once screening lets it through, then the answer."""

    def question(self) -> None:
        """Write the question; called when the screen node ends without stopping the run."""

    def answer(self, state: AgentState, events: list[EventModel]) -> None:
        """Write the answer; called with the final state and every answer event before the last are sent."""


def answer_text(state: AgentState, events: list[EventModel]) -> str:
    """What the user reads as the answer: the summary, clarifying question, denial or error message."""
    if state.get("summary"):
        return state["summary"]
    for event in events:
        if isinstance(event, SummaryEvent):
            return event.text
        if isinstance(event, ClarifyEvent):
            return event.question
        if isinstance(event, DenyEvent | ErrorEvent | BlockedEvent):
            return event.message
    return ""


class StoredTurn:
    """The turn of ``store`` a question opened; an answer is stored only after its question."""

    def __init__(self, store: ConversationStore, turn: OpenTurn):
        self._store = store
        self._turn = turn
        self.asked = False

    def question(self) -> None:
        self._store.question(self._turn)
        self.asked = True

    def answer(self, state: AgentState, events: list[EventModel]) -> None:
        if not self.asked:
            return
        self._store.answer(
            self._turn, trace_id=state["trace_id"], content=answer_text(state, events), query_spec=state.get("spec"),
            result=state.get("result"), events=events,
        )


async def event_stream(
    run: AgentRun, question: str, events: AnswerEvents, heartbeat_seconds: float = HEARTBEAT_SECONDS,
    record: Record | None = None,
) -> AsyncIterator[str]:
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[EventModel | None] = asyncio.Queue()
    stopped = threading.Event()

    def put(item: EventModel | None) -> None:
        try:
            loop.call_soon_threadsafe(queue.put_nowait, item)
        except RuntimeError:  # the stream is gone and its loop closed
            pass

    def progress(name, phase, state, update) -> None:
        if stopped.is_set():
            raise RunCancelled()
        for event in events.node(name, phase, state, update):
            put(event)
        if record is not None and name == "screen" and phase == "end" and update is not None and not update.get("blocked"):
            try:
                record.question()
            except Exception:  # noqa: BLE001 - the answer still reaches the client; the conversation lacks the turn
                logger.exception("could not store the question of trace %s", events.trace_id)

    def work() -> None:
        try:
            state = run.run(question, progress)
            closing = events.finish(state)
            if record is not None:
                try:
                    record.answer(state, events.answered)
                except Exception:  # noqa: BLE001 - the answer still reaches the client; the next turn lacks it
                    logger.exception("could not store the answer of trace %s", events.trace_id)
            for event in closing:
                put(event)
        except RunCancelled:
            pass
        except Exception:
            logger.exception("the run of trace %s failed", events.trace_id or "(none)")
            for event in events.internal():
                put(event)
        finally:
            put(None)

    loop.run_in_executor(None, work)
    finished = False
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), heartbeat_seconds)
            except TimeoutError:
                yield ": keep-alive\n\n"
                continue
            if item is None:
                finished = True
                return
            yield frame(item)
            if item.event in TERMINAL:
                finished = True
                return
    finally:
        if not finished:
            stopped.set()
            loop.run_in_executor(None, run.cancel)


def rate_limited(
    principal: Annotated[Principal, Depends(current_principal)],
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> None:
    wait = limiter.acquire(principal.user_id)
    if wait > 0:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, detail="too many questions; try again shortly",
            headers={"Retry-After": str(math.ceil(wait))},
        )


@router.post("/ask", response_class=StreamingResponse)
def ask(
    request: AskRequest,
    principal: Annotated[Principal, Depends(current_principal)],
    role: Annotated[str, Depends(current_role)],
    _: Annotated[None, Depends(rate_limited)],
    agent: Annotated[Agent, Depends(get_agent)],
    store: Annotated[ConversationStore, Depends(get_conversation_store)],
) -> StreamingResponse:
    try:
        today = reference_date(request.timezone)
    except TimeResolutionError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from None
    try:
        turn = store.open_turn(
            principal.user_id, request.conversation_id, request.question,
            edit_of_turn=request.edit_of_turn, retry_of_turn=request.retry_of_turn,
        )
    except ConversationNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="conversation not found") from None
    except TurnNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="turn not found in the conversation") from None
    except Exception:  # noqa: BLE001 - ClickHouse is unreachable or refused the conversation tables
        logger.exception("cannot open a conversation turn")
        raise unavailable("the conversation store is unavailable") from None
    try:
        run = agent.start(role=role, user_id=principal.user_id, today=today, history=turn.history)
    except Exception:  # noqa: BLE001 - the role's ClickHouse client could not be created
        logger.exception("cannot prepare a run as role %s", role)
        raise unavailable("the agent cannot reach its data store") from None
    return StreamingResponse(
        event_stream(run, turn.question, AnswerEvents(role), record=StoredTurn(store, turn)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "X-Conversation-Id": turn.conversation_id},
    )
