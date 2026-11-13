"""The console's Users section on local accounts (DECISIONS §9, §15).

Only an ``admin`` reaches these endpoints. An account holds roles of the
active pack and console roles; any other role is refused. Every change is
recorded in ``agent_logs.admin_actions`` (a password change records no value)
and reaches the user's next request: the principal is read from the account
on each request, and disabling the account or resetting its password signs the user out
everywhere. The last enabled admin cannot be disabled or demoted.
"""

import json
from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.console import require_admin
from app.api.runtime import get_admin_action_log, get_compiled_or_none, get_state_db, pack_identity
from app.auth import accounts
from app.auth.principal import Principal
from app.auth.roles import CONSOLE_ROLES, known_roles
from app.contracts.users import NewUser, PasswordReset, UserChange, UserView
from app.observability.events import AdminActionRecord, utc_now
from app.packs.compiler import CompiledPack
from app.state.db import StateDb

router = APIRouter(prefix="/admin/users")
Admin = Annotated[Principal, Depends(require_admin)]
Compiled = Annotated[CompiledPack | None, Depends(get_compiled_or_none)]
State = Annotated[StateDb, Depends(get_state_db)]


class ActionLog(Protocol):
    def record_action(self, record: AdminActionRecord) -> None: ...


Log = Annotated[ActionLog, Depends(get_admin_action_log)]


def _view(account: accounts.Account, pack_roles: list[str]) -> UserView:
    return UserView(id=account.id, email=account.email, display_name=account.display_name,
                    roles=known_roles(account.roles, pack_roles), enabled=account.enabled)


def _check_roles(roles: list[str], pack_roles: list[str]) -> None:
    unknown = sorted(set(roles) - set(pack_roles) - set(CONSOLE_ROLES))
    if unknown:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"not roles of this instance: {', '.join(unknown)}")


def _refusal(error: accounts.AccountError) -> HTTPException:
    code = {
        accounts.UnknownAccount: status.HTTP_404_NOT_FOUND,
        accounts.DuplicateEmail: status.HTTP_409_CONFLICT,
        accounts.LastAdmin: status.HTTP_409_CONFLICT,
    }.get(type(error), status.HTTP_422_UNPROCESSABLE_CONTENT)
    return HTTPException(code, detail=str(error))


def _record(log: ActionLog, admin: Principal, action: str, target: str, old: Any, new: Any) -> None:
    log.record_action(AdminActionRecord(ts=utc_now(), actor=admin.user_id, action=action, target=target,
                                        old_value=json.dumps(old), new_value=json.dumps(new)))


@router.get("")
def list_users(_: Admin, db: State, compiled: Compiled) -> list[UserView]:
    roles = pack_identity(compiled).roles
    return [_view(account, roles) for account in accounts.list_all(db)]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_user(body: NewUser, admin: Admin, db: State, compiled: Compiled, log: Log) -> UserView:
    pack_roles = pack_identity(compiled).roles
    _check_roles(body.roles, pack_roles)
    try:
        account = accounts.create(db, body.email, body.display_name, body.password, body.roles)
    except accounts.AccountError as error:
        raise _refusal(error) from None
    view = _view(account, pack_roles)
    _record(log, admin, "user_created", account.id, None, {"email": view.email, "roles": view.roles})
    return view


@router.patch("/{user_id}")
def change_user(user_id: str, body: UserChange, admin: Admin, db: State, compiled: Compiled, log: Log) -> UserView:
    pack_roles = pack_identity(compiled).roles
    if body.roles is not None:
        _check_roles(body.roles, pack_roles)
    before = accounts.get(db, user_id)
    if before is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="account not found")
    try:
        after = accounts.update(db, user_id, display_name=body.display_name, roles=body.roles, enabled=body.enabled)
    except accounts.AccountError as error:
        raise _refusal(error) from None
    old, new = _view(before, pack_roles), _view(after, pack_roles)
    for field, action in (("display_name", "user_display_name"), ("roles", "user_roles"), ("enabled", "user_enabled")):
        if getattr(old, field) != getattr(new, field):
            _record(log, admin, action, user_id, getattr(old, field), getattr(new, field))
    return new


@router.post("/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(user_id: str, body: PasswordReset, admin: Admin, db: State, log: Log) -> Response:
    try:
        accounts.set_password(db, user_id, body.password)
    except accounts.AccountError as error:
        raise _refusal(error) from None
    _record(log, admin, "user_password", user_id, None, None)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
