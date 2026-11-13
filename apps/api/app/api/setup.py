"""The first-run setup (DECISIONS §15): who uses the instance, and when setup is complete.

The changes need the ``admin`` role: the owner holds it in individual mode.
The status is readable by any user so that the web app can tell a user who is
not an admin that the instance is still being set up. Moving from individual
to team mode creates the first admin from the request and signs the caller in
as that admin; moving back is refused while more than one account is enabled.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.api.auth import current_principal
from app.api.console import require_admin
from app.api.runtime import get_compiled_or_none, get_state_db, pack_identity
from app.api.session import sign_in_response
from app.auth import accounts
from app.auth.principal import Principal
from app.contracts.setup import SetupModeChange, SetupStatus, SetupStep
from app.packs.compiler import CompiledPack
from app.state import setup
from app.state.db import StateDb

router = APIRouter(prefix="/setup")
Admin = Annotated[Principal, Depends(require_admin)]
Compiled = Annotated[CompiledPack | None, Depends(get_compiled_or_none)]


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
def put_mode(
    change: SetupModeChange, _: Admin, db: State, compiled: Compiled, request: Request, response: Response,
) -> SetupStatus:
    first_admin = None if change.admin is None else setup.FirstAdmin(**change.admin.model_dump())
    try:
        created = setup.set_mode(db, change.mode, first_admin, pack_identity_roles(compiled))
    except (setup.TooManyAccounts, accounts.DuplicateEmail) as error:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(error)) from None
    except (setup.SetupError, accounts.AccountError) as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from None
    if created is not None:
        sign_in_response(request, response, db, created.id)
    return _view(db)


def pack_identity_roles(compiled: CompiledPack | None) -> list[str]:
    try:
        return pack_identity(compiled).roles
    except HTTPException:
        return []


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
