"""The principal of every request, plus ``/me`` and ``/pack``.

``current_principal`` returns the owner in individual mode and otherwise
reads the session cookie of a signed-in account. It answers 401 for a
missing, unknown or expired session and never says which check failed; ``current_role`` answers 403 when the
principal holds no pack role or the ``X-Active-Role`` header names one it does
not hold. ``/pack`` is public: the sign-in screen names the active pack.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, status
from pydantic import BaseModel

from app.api.runtime import (
    PackIdentity, get_compiled, get_compiled_or_none, get_pack_identity, get_state_db, pack_identity,
)
from app.auth import account_sessions, origin
from app.auth.principal import SESSION_COOKIE, Principal, owner
from app.auth.roles import RoleError, active_role, known_roles
from app.packs.compiler import CompiledPack
from app.state.db import StateDb

router = APIRouter()

UNAUTHORIZED = HTTPException(status.HTTP_401_UNAUTHORIZED, detail="sign in again")


def pack_roles(compiled: CompiledPack) -> list[str]:
    return [role.id for role in compiled.pack.policies.roles]


def _owner_pack_roles(compiled: Annotated[CompiledPack | None, Depends(get_compiled_or_none)]) -> list[str]:
    """The pack roles the owner holds; none while no pack is configured."""
    try:
        return pack_identity(compiled).roles
    except HTTPException:
        return []


def current_principal(
    db: Annotated[StateDb, Depends(get_state_db)],
    owner_roles: Annotated[list[str], Depends(_owner_pack_roles)],
    session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> Principal:
    if origin.instance_mode(db) == origin.INDIVIDUAL:
        # The address checks of app/auth/origin.py are the gate; there is no sign-in.
        return owner(owner_roles)
    principal = account_sessions.principal_for(db, session) if session else None
    if principal is None:
        raise UNAUTHORIZED
    return principal


def current_role(
    principal: Annotated[Principal, Depends(current_principal)],
    compiled: Annotated[CompiledPack, Depends(get_compiled)],
    x_active_role: Annotated[str | None, Header()] = None,
) -> str:
    try:
        return active_role(principal.roles, pack_roles(compiled), x_active_role)
    except RoleError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=str(error)) from None


class Me(BaseModel):
    user_id: str
    display_name: str
    roles: list[str]
    active_role: str | None
    mode: Literal["individual", "team"]
    # Individual mode reachable through a name other than loopback: the interface shows a standing warning.
    exposed: bool


class PackInfo(BaseModel):
    name: str
    display_name: str
    roles: list[str]


@router.get("/me")
def me(
    principal: Annotated[Principal, Depends(current_principal)],
    identity: Annotated[PackIdentity, Depends(get_pack_identity)],
    db: Annotated[StateDb, Depends(get_state_db)],
    x_active_role: Annotated[str | None, Header()] = None,
) -> Me:
    """The user a request acts as; ``active_role`` is null for a user who holds console roles only."""
    roles = identity.roles
    try:
        role = active_role(principal.roles, roles, x_active_role)
    except RoleError as error:
        if x_active_role is not None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail=str(error)) from None
        role = None
    mode = origin.instance_mode(db)
    return Me(
        user_id=principal.user_id, display_name=principal.display_name,
        roles=known_roles(principal.roles, roles), active_role=role, mode=mode,
        exposed=mode == origin.INDIVIDUAL and origin.exposed(),
    )


@router.get("/pack")
def pack(identity: Annotated[PackIdentity, Depends(get_pack_identity)]) -> PackInfo:
    """The active pack, from its pack files while it was never compiled."""
    return PackInfo(name=identity.name, display_name=identity.display_name, roles=identity.roles)
