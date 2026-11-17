"""``/settings/limits``: read and change how many questions the api answers at once (app/api/limits.py)."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.console import require_admin
from app.api.runtime import get_state_db
from app.auth.principal import Principal
from app.contracts.limits import LimitSettings
from app.state.db import StateDb
from app.state.settings import Settings

router = APIRouter(prefix="/settings/limits")
Admin = Annotated[Principal, Depends(require_admin)]
State = Annotated[StateDb, Depends(get_state_db)]


@router.get("")
def get_limits(_: Admin, db: State) -> LimitSettings:
    return LimitSettings(concurrent_questions=Settings(db).get("limits", "concurrent_questions"))


@router.put("")
def put_limits(change: LimitSettings, _: Admin, db: State) -> LimitSettings:
    """The new limit applies to the next question that queues; questions already running finish."""
    Settings(db).set("limits", "concurrent_questions", change.concurrent_questions)
    return change
