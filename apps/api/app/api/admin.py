"""The console's Runs and trace, Audit and Costs sections, and admin reads of conversations (DECISIONS §15).

Every endpoint is read-only and answers only an ``admin``. Dates are ISO days;
``to`` is exclusive. An admin reads any user's conversations, including the
ones their owner deleted, which are marked ``deleted``.
"""

from datetime import date, timedelta
import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.console import require_admin
from app.api.runtime import get_admin_logs, unavailable
from app.auth.principal import Principal
from app.contracts.admin import (
    AdminConversation, AdminConversationThread, AuditRow, CostRow, RunRow, RunTrace, ScreeningRow,
)
from app.admin.logs import AdminLogs

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin")
Admin = Annotated[Principal, Depends(require_admin)]
Logs = Annotated[AdminLogs, Depends(get_admin_logs)]
COST_DAYS = 30


def _read(call):
    try:
        return call()
    except Exception as error:  # noqa: BLE001 - ClickHouse unreachable or refused the reader
        logger.error("an admin log read failed", exc_info=error)
        raise unavailable("the run logs are unavailable") from None


@router.get("/runs")
def list_runs(
    _: Admin, logs: Logs, user: str | None = None, status_filter: Annotated[str | None, Query(alias="status")] = None,
    start: Annotated[date | None, Query(alias="from")] = None, end: Annotated[date | None, Query(alias="to")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
) -> list[RunRow]:
    return _read(lambda: logs.runs(user=user, start=start, end=end, status=status_filter, page=page))


@router.get("/runs/{trace_id}")
def read_trace(trace_id: str, _: Admin, logs: Logs) -> RunTrace:
    trace = _read(lambda: logs.trace(trace_id))
    if trace is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="run not found")
    return trace


@router.get("/audit")
def list_audit(
    _: Admin, logs: Logs, decision: Literal["ALLOW", "DENY"] | None = None, page: Annotated[int, Query(ge=1)] = 1,
) -> list[AuditRow]:
    return _read(lambda: logs.audit(decision=decision, page=page))


@router.get("/screening")
def list_screening(
    _: Admin, logs: Logs, verdict: str | None = None, source: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
) -> list[ScreeningRow]:
    return _read(lambda: logs.screening(verdict=verdict, source=source, page=page))


@router.get("/costs")
def list_costs(
    _: Admin, logs: Logs, start: Annotated[date | None, Query(alias="from")] = None,
    end: Annotated[date | None, Query(alias="to")] = None,
) -> list[CostRow]:
    end = end or date.today() + timedelta(days=1)
    start = start or end - timedelta(days=COST_DAYS)
    return _read(lambda: logs.costs(start=start, end=end))


@router.get("/conversations")
def list_conversations(_: Admin, logs: Logs, user: str | None = None) -> list[AdminConversation]:
    return _read(lambda: logs.conversations(user=user))


@router.get("/conversations/{conversation_id}")
def read_conversation(conversation_id: str, _: Admin, logs: Logs) -> AdminConversationThread:
    thread = _read(lambda: logs.conversation(conversation_id))
    if thread is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="conversation not found")
    return thread
