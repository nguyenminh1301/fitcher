"""``POST /ask``: answer one question as a stream of server-sent events (DECISIONS §6).

The request is authenticated and rate limited, then served from its pack: the
pack of the conversation it continues, else the ``pack`` it names (one pack
per data source), else the pack used last; it is mapped to its role in that
pack before the graph starts. The question then opens a turn of its
conversation: a new one, on that pack, when the request names none, otherwise
one the user owns, or 404; an edit
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
disconnects, the run goes on and stores its answer (``app.api.live_runs``): leaving
the page never loses an answer. ``POST /conversations/{id}/stop`` stops it at its
next node and kills the ClickHouse query it may be running.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from collections.abc import AsyncIterator, Mapping, Sequence
import logging
import math
import threading
from typing import Annotated, Literal, Protocol
from uuid import uuid4

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.agent.nodes.resolve_time import TimeResolutionError, reference_date
from app.agent.nodes.screen import blocked_message, question_language
from app.agent.state import AgentState, RunCancelled
from app.api.agent import Agent, AgentRun
from app.api.auth import current_principal, pack_roles
from app.api.limits import QuestionGate
from app.api.live_runs import LIVE_RUNS, LiveRun, LiveRuns
from app.api.rate_limit import RateLimiter
from app.api import runtime
from app.api.runtime import get_conversation_store, get_question_gate, get_rate_limiter, unavailable
from app.auth.principal import Principal
from app.auth.roles import active_role, RoleError
from app.packs.active import set_active_pack
from app.packs.compiler import CompiledPack
from app.contracts.events import (
    AskRequest, BlockedEvent, ChartSpecEvent, ClarifyEvent, DenyEvent, DoneEvent, ErrorEvent, EventModel, ResultEvent,
    SqlEvent, StatusEvent, SummaryEvent,
)
from app.conversation.store import ConversationNotFound, ConversationStore, OpenTurn, Turn, TurnNotFound, shown_events

logger = logging.getLogger(__name__)
router = APIRouter()

HEARTBEAT_SECONDS = 15.0
INTERNAL_ERROR = "The answer could not be completed because of an internal error."
TERMINAL = frozenset({"done", "error"})


def _language(state: Mapping) -> str:
    return question_language(state)


def unreviewed_metrics(compiled) -> frozenset[str]:
    """The compiled pack's metrics an instant pack approved without a person."""
    return frozenset(metric.id for metric in compiled.pack.metrics.metrics if metric.reviewed is False)


class AnswerEvents:
    """The events of one run, from graph progress and the final state."""

    def __init__(self, role: str, unreviewed_metrics: frozenset[str] = frozenset()):
        self.role = role
        # The pack's metrics marked ``reviewed: false``: an instant pack approved them without a person.
        self.unreviewed_metrics = unreviewed_metrics
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
            spec = state.get("spec")
            unreviewed = [metric for metric in (spec.metric_ids if spec else []) if metric in self.unreviewed_metrics]
            events.append(SqlEvent(**trace, sql=attempts[-1].sql, attempt=len(attempts), unreviewed_metrics=unreviewed))
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
            return [ClarifyEvent(
                **trace, question=asked.question, options=asked.options, lang=asked.lang,
                about=state["question"], chosen=list(state.get("choices", [])),
            ), DoneEvent(**trace)]
        if state.get("model_error"):
            # The model did not answer: the client says so in its own language and offers to try again.
            return [ErrorEvent(**trace, kind="model", message="The model did not answer.", error=state["model_error"])]
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


def picked_option(history: Sequence[Turn], option: str) -> tuple[str, tuple[str, ...]] | None:
    """The clarified question and every option picked for it when ``option`` answers the last turn's clarifying
    question; None when the last turn asked nothing or offered no such option, and the question is read as typed."""
    if not history or not history[-1].events:
        return None
    for event in shown_events(history[-1]):
        if isinstance(event, ClarifyEvent) and any(choice.id == option for choice in event.options):
            return event.about or history[-1].question, (*event.chosen, option)
    return None


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


# Questions run, or wait for a place, on their own threads: the event loop's default executor holds only
# min(32, CPUs + 4) threads, which on a small host is fewer than the questions limits.concurrent_questions
# lets run plus those waiting in order (docs/operations.md, load measurement).
QUESTION_THREADS = ThreadPoolExecutor(max_workers=128, thread_name_prefix="question")


async def event_stream(
    run: AgentRun, question: str, events: AnswerEvents, heartbeat_seconds: float = HEARTBEAT_SECONDS,
    record: Record | None = None, gate: QuestionGate | None = None,
    live: tuple[LiveRuns, str, str] | None = None,
) -> AsyncIterator[str]:
    """The run's events; ``live`` is the registry, user and conversation that let the run be stopped by request."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[EventModel | None] = asyncio.Queue()
    stopped = threading.Event()
    entry = LiveRun(user_id=live[1], stopped=stopped, cancel=run.cancel) if live is not None else None
    if live is not None and entry is not None:
        live[0].add(live[2], entry)

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

    def queued(phase: Literal["start", "end"]) -> None:
        put(StatusEvent(trace_id=events.trace_id, node="queue", phase=phase))

    def work() -> None:
        admitted = None
        try:
            if gate is not None:
                admitted = gate.enter(lambda: queued("start"), stopped.is_set)
                if admitted is None:
                    return
                if admitted:
                    queued("end")
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
            if gate is not None and admitted is not None:
                gate.leave()
            if live is not None and entry is not None:
                live[0].finish(live[2], entry)
            put(None)

    loop.run_in_executor(QUESTION_THREADS, work)
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
        # A stream closed before the end stops a run that nobody can find again; a run of a conversation goes on.
        if not finished and live is None:
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


def _served(pack: str, build: Callable[[], object]):
    with runtime.serving(pack):
        return build()


def get_compiled_for() -> Callable[[str], CompiledPack]:
    """The compiled pack of a name; 503 when it was never compiled."""
    return lambda pack: _served(pack, runtime.get_compiled)


def get_agent_for() -> Callable[[str], Agent]:
    """The agent of a pack, kept per pack."""
    return lambda pack: _served(pack, runtime.get_agent)


def _remember(pack: str) -> None:
    """The pack asked last is where a new chat starts; failing to record it never fails the question."""
    try:
        if runtime.last_used_pack() != pack:
            set_active_pack(runtime.get_state_db(), pack)
    except Exception:  # noqa: BLE001 - the app state is busy or unwritable
        logger.warning("the last used pack was not recorded")


def get_remember_pack() -> Callable[[str], None]:
    return _remember


def get_last_used_pack() -> str:
    return runtime.last_used_pack()


def _pack_of(request: AskRequest, user_id: str, store: ConversationStore, last_used: str) -> str:
    """The conversation's pack, else the pack the request names, else the pack used last."""
    if request.conversation_id is None:
        pack = request.pack or last_used
    else:
        try:
            pack = store.pack_of(user_id, request.conversation_id) or last_used
        except ConversationNotFound:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="conversation not found") from None
        except Exception:  # noqa: BLE001 - ClickHouse is unreachable or refused the conversation tables
            logger.exception("cannot read the conversation's pack")
            raise unavailable("the conversation store is unavailable") from None
    if not pack:
        raise unavailable("no pack is active: connect a source and build its pack, or set ACTIVE_PACK")
    return pack


@router.post("/ask", response_class=StreamingResponse)
def ask(
    request: AskRequest,
    principal: Annotated[Principal, Depends(current_principal)],
    _: Annotated[None, Depends(rate_limited)],
    compiled_for: Annotated[Callable[[str], CompiledPack], Depends(get_compiled_for)],
    agent_for: Annotated[Callable[[str], Agent], Depends(get_agent_for)],
    remember: Annotated[Callable[[str], None], Depends(get_remember_pack)],
    last_used: Annotated[str, Depends(get_last_used_pack)],
    store: Annotated[ConversationStore, Depends(get_conversation_store)],
    gate: Annotated[QuestionGate, Depends(get_question_gate)],
) -> StreamingResponse:
    try:
        today = reference_date(request.timezone)
    except TimeResolutionError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from None
    pack = _pack_of(request, principal.user_id, store, last_used)
    try:
        role = active_role(principal.roles, pack_roles(compiled_for(pack)))
    except RoleError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=str(error)) from None
    agent = agent_for(pack)
    try:
        turn = store.open_turn(
            principal.user_id, request.conversation_id, request.question,
            edit_of_turn=request.edit_of_turn, retry_of_turn=request.retry_of_turn, pack=pack,
        )
    except ConversationNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="conversation not found") from None
    except TurnNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="turn not found in the conversation") from None
    except Exception:  # noqa: BLE001 - ClickHouse is unreachable or refused the conversation tables
        logger.exception("cannot open a conversation turn")
        raise unavailable("the conversation store is unavailable") from None
    try:
        clarified = picked_option(turn.history, request.clarify_option) if request.clarify_option else None
        run = agent.start(role=role, user_id=principal.user_id, today=today, history=turn.history, clarified=clarified)
    except Exception:  # noqa: BLE001 - the role's ClickHouse client could not be created
        logger.exception("cannot prepare a run as role %s", role)
        raise unavailable("the agent cannot reach its data store") from None
    remember(pack)
    return StreamingResponse(
        event_stream(run, turn.question, AnswerEvents(role, unreviewed_metrics(run.deps.compiled)), record=StoredTurn(store, turn),
                     gate=gate, live=(LIVE_RUNS, principal.user_id, turn.conversation_id)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "X-Conversation-Id": turn.conversation_id},
    )


@router.post("/conversations/{conversation_id}/stop", status_code=status.HTTP_204_NO_CONTENT)
def stop_answer(conversation_id: str, principal: Annotated[Principal, Depends(current_principal)]) -> None:
    """Stop the question the conversation is answering; 404 when none of the user's is running."""
    if not LIVE_RUNS.stop(principal.user_id, conversation_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="no question of this conversation is running")
