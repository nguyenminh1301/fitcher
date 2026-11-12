"""The first-run setup (DECISIONS §15): who uses the instance, and when setup is complete.

Until sign-in moves into the app (Phase 15) the changes need the ``admin``
role of the existing sign-in. The status is readable by any signed-in user so
that the web app can tell a user who is not an admin that the instance is
still being set up.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.auth import current_principal
from app.api.console import require_admin
from app.auth.jwt import Principal
from app.contracts.setup import SetupModeChange, SetupStatus, SetupStep
from app.state import setup
from app.state.db import StateDb, shared_state

router = APIRouter(prefix="/setup")
Admin = Annotated[Principal, Depends(require_admin)]


def get_state_db() -> StateDb:
    return shared_state()


State = Annotated[StateDb, Depends(get_state_db)]


def _view(db: StateDb) -> SetupStatus:
    current = setup.status(db)
    return SetupStatus(
        mode=current.mode, steps=[SetupStep(id=s.id, state=s.state) for s in current.steps], complete=current.complete
    )


@router.get("/status")
def get_status(_: Annotated[Principal, Depends(current_principal)], db: State) -> SetupStatus:
    return _view(db)


@router.put("/mode")
def put_mode(change: SetupModeChange, _: Admin, db: State) -> SetupStatus:
    setup.set_mode(db, change.mode)
    return _view(db)


@router.post("/steps/{step_id}/skip")
def skip_step(step_id: str, _: Admin, db: State) -> SetupStatus:
    try:
        setup.skip(db, step_id)
    except setup.UnknownStep as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(error)) from None
    return _view(db)


@router.post("/complete")
def complete_setup(_: Admin, db: State) -> SetupStatus:
    try:
        setup.complete(db)
    except setup.SetupError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(error)) from None
    return _view(db)
