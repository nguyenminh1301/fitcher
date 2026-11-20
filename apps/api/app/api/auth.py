"""The principal of every request, plus ``/me`` and ``/pack``.

fitcher is a personal app (DECISIONS §9): ``current_principal`` is always the owner, and the address checks of
``app/auth/origin.py`` decide who reaches the api. ``current_role`` answers 403 when the ``X-Active-Role``
header names a pack role the owner does not hold.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel

from app.api import runtime
from app.api.runtime import (
    PackIdentity, get_compiled, get_compiled_or_none, get_pack_identity, get_pack_identity_or_none,
    pack_identity,
)
from app.auth import origin
from app.auth import owner as owner_password
from app.auth.principal import Principal, owner
from app.auth.roles import RoleError, active_role, known_roles
from app.packs.compiler import CompiledPack

router = APIRouter()


def pack_roles(compiled: CompiledPack) -> list[str]:
    return [role.id for role in compiled.pack.policies.roles]


def _owner_pack_roles(compiled: Annotated[CompiledPack | None, Depends(get_compiled_or_none)]) -> list[str]:
    """The pack roles the owner holds; none while no pack is configured."""
    try:
        return pack_identity(compiled).roles
    except HTTPException:
        return []


def current_principal(owner_roles: Annotated[list[str], Depends(_owner_pack_roles)]) -> Principal:
    return owner(owner_roles)


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
    # Reachable through a name other than loopback while no owner password is set: anyone who can reach the name
    # controls the instance, so the interface shows a standing warning. A password set ends the warning.
    exposed: bool


class PackInfo(BaseModel):
    name: str
    display_name: str
    roles: list[str]


@router.get("/me")
def me(
    principal: Annotated[Principal, Depends(current_principal)],
    identity: Annotated[PackIdentity | None, Depends(get_pack_identity_or_none)],
    x_active_role: Annotated[str | None, Header()] = None,
) -> Me:
    """The user a request acts as; ``active_role`` is null for a user who holds console roles only, as on a new
    instance where no pack is active yet."""
    roles = identity.roles if identity is not None else []
    try:
        role = active_role(principal.roles, roles, x_active_role)
    except RoleError as error:
        if x_active_role is not None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail=str(error)) from None
        role = None
    return Me(
        user_id=principal.user_id, display_name=principal.display_name,
        roles=known_roles(principal.roles, roles), active_role=role, exposed=origin.exposed() and not _password_set(),
    )


def _password_set() -> bool:
    """Whether the owner password is set; an unreadable app state keeps the warning, which is the safe side."""
    try:
        return owner_password.password_set(runtime.get_state_db())
    except Exception:  # noqa: BLE001 - only the warning depends on it
        return False


@router.get("/pack")
def pack(identity: Annotated[PackIdentity, Depends(get_pack_identity)]) -> PackInfo:
    """The active pack, from its pack files while it was never compiled."""
    return PackInfo(name=identity.name, display_name=identity.display_name, roles=identity.roles)


SUGGESTIONS = 3


class PackChoice(BaseModel):
    name: str


@router.put("/pack")
def choose_pack(choice: PackChoice, _: Annotated[Principal, Depends(current_principal)]) -> PackInfo:
    """Make a compiled pack the current one: the console reads it and a new conversation starts on it."""
    if not runtime.PACK_NAME.fullmatch(choice.name):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="name must be a pack name")
    with runtime.serving(choice.name):
        identity = pack_identity(runtime.get_compiled())
    runtime.set_active_pack(runtime.get_state_db(), choice.name)
    return PackInfo(name=identity.name, display_name=identity.display_name, roles=identity.roles)


@router.get("/pack/suggestions")
def suggestions(
    principal: Annotated[Principal, Depends(current_principal)],
    compiled: Annotated[CompiledPack, Depends(get_compiled)],
) -> list[dict[str, str]]:
    """The first approved example questions of the compiled pack, offered in an empty chat (DECISIONS §11 step 0)."""
    return [{"text": example.question, "lang": example.language} for example in compiled.pack.examples.examples[:SUGGESTIONS]]
