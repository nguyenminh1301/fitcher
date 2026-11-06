"""The console's Users section: realm users, their pack roles, and enabling them (DECISIONS §9, §15).

Only an ``admin`` reaches these endpoints. Roles are the active pack's policy
roles only; console roles and Keycloak's own roles are left as they are. The
api refuses any change to the acting admin's own account, never creates or
deletes users or sets credentials, and records every change in
``agent_logs.admin_actions``. A role change reaches the user's next access
token, at the latest when the current one expires.
"""

import json
import logging
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.console import require_admin
from app.api.runtime import get_admin_action_log, get_compiled_or_none, get_keycloak_admin, pack_identity, unavailable
from app.auth.jwt import Principal
from app.auth.keycloak_admin import KeycloakAdmin, KeycloakAdminError, RealmUser
from app.contracts.users import UserRoles, UserView
from app.observability.events import AdminActionRecord, utc_now
from app.packs.compiler import CompiledPack

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/users")
Admin = Annotated[Principal, Depends(require_admin)]
Keycloak = Annotated[KeycloakAdmin, Depends(get_keycloak_admin)]
Compiled = Annotated[CompiledPack | None, Depends(get_compiled_or_none)]


class ActionLog(Protocol):
    def record_action(self, record: AdminActionRecord) -> None: ...


Log = Annotated[ActionLog, Depends(get_admin_action_log)]


def _view(user: RealmUser, pack_roles: list[str]) -> UserView:
    return UserView(id=user.id, username=user.username, display_name=user.display_name,
                    roles=[role for role in pack_roles if role in user.roles], enabled=user.enabled)


def _refusal(error: KeycloakAdminError) -> HTTPException:
    if str(error) == "user not found":
        return HTTPException(status.HTTP_404_NOT_FOUND, detail="user not found")
    logger.error("a Keycloak Admin API call failed: %s", error)
    return unavailable("user administration is unavailable")


def _not_self(admin: Principal, user: RealmUser) -> None:
    if user.username == admin.user_id or user.id == admin.subject:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="an admin cannot change their own account")


def _record(log: ActionLog, admin: Principal, action: str, user: RealmUser, old, new) -> None:
    log.record_action(AdminActionRecord(ts=utc_now(), actor=admin.user_id, action=action, target=user.id,
                                        old_value=json.dumps(old), new_value=json.dumps(new)))


@router.get("")
def list_users(_: Admin, keycloak: Keycloak, compiled: Compiled) -> list[UserView]:
    roles = pack_identity(compiled).roles
    try:
        return [_view(user, roles) for user in keycloak.users()]
    except KeycloakAdminError as error:
        raise _refusal(error) from None


@router.put("/{user_id}/roles")
def set_roles(user_id: str, body: UserRoles, admin: Admin, keycloak: Keycloak, compiled: Compiled, log: Log) -> UserView:
    pack_roles = pack_identity(compiled).roles
    unknown = sorted(set(body.roles) - set(pack_roles))
    if unknown:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"not roles of this pack: {', '.join(unknown)}")
    try:
        user = keycloak.user(user_id)
        _not_self(admin, user)
        old = [role for role in pack_roles if role in user.roles]
        keycloak.set_roles(user_id, add=set(body.roles) - set(old), remove=set(old) - set(body.roles))
        _record(log, admin, "user_roles", user, old, [role for role in pack_roles if role in body.roles])
        return _view(keycloak.user(user_id), pack_roles)
    except KeycloakAdminError as error:
        raise _refusal(error) from None


def _set_enabled(user_id: str, enabled: bool, admin: Principal, keycloak: KeycloakAdmin, log: ActionLog) -> Response:
    try:
        user = keycloak.user(user_id)
        _not_self(admin, user)
        keycloak.set_enabled(user_id, enabled)
        _record(log, admin, "user_enabled", user, user.enabled, enabled)
    except KeycloakAdminError as error:
        raise _refusal(error) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{user_id}/disable", status_code=status.HTTP_204_NO_CONTENT)
def disable(user_id: str, admin: Admin, keycloak: Keycloak, log: Log) -> Response:
    return _set_enabled(user_id, False, admin, keycloak, log)


@router.post("/{user_id}/enable", status_code=status.HTTP_204_NO_CONTENT)
def enable(user_id: str, admin: Admin, keycloak: Keycloak, log: Log) -> Response:
    return _set_enabled(user_id, True, admin, keycloak, log)
