"""The principal of every request, plus ``/me`` and ``/pack``.

``current_principal`` reads the session cookie of a signed-in account. While
the web app still signs in through Keycloak, a request without the cookie may
send a Keycloak bearer token instead; that path goes when Keycloak is removed.
It answers 401 for a missing, unknown or expired session or a refused token and
never says which check failed; ``current_role`` answers 403 when the
principal holds no pack role or the ``X-Active-Role`` header names one it does
not hold. ``/pack`` is public: the sign-in screen names the active pack.
"""

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, status
from pydantic import BaseModel

from app.api.runtime import PackIdentity, get_compiled, get_pack_identity, get_state_db, get_verifier, unavailable
from app.auth import sessions
from app.auth.jwt import AuthError, AuthUnavailable, TokenVerifier
from app.auth.principal import SESSION_COOKIE, Principal
from app.auth.roles import RoleError, active_role, known_roles
from app.packs.compiler import CompiledPack
from app.state.db import StateDb

router = APIRouter()

UNAUTHORIZED = HTTPException(
    status.HTTP_401_UNAUTHORIZED, detail="invalid or expired access token", headers={"WWW-Authenticate": "Bearer"},
)


def pack_roles(compiled: CompiledPack) -> list[str]:
    return [role.id for role in compiled.pack.policies.roles]


def current_principal(
    db: Annotated[StateDb, Depends(get_state_db)],
    verifier: Annotated[TokenVerifier | None, Depends(get_verifier)],
    session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> Principal:
    if session is not None:
        principal = sessions.principal_for(db, session)
        if principal is None:
            raise UNAUTHORIZED
        return principal
    scheme, _, credentials = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not credentials.strip():
        raise UNAUTHORIZED
    if verifier is None:
        raise unavailable("KEYCLOAK_ISSUER, KEYCLOAK_AUDIENCE and KEYCLOAK_JWKS_URL must be set")
    try:
        return verifier.verify(credentials.strip())
    except AuthError:
        raise UNAUTHORIZED from None
    except AuthUnavailable as error:
        raise unavailable(str(error)) from None


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


class PackInfo(BaseModel):
    name: str
    display_name: str
    roles: list[str]


@router.get("/me")
def me(
    principal: Annotated[Principal, Depends(current_principal)],
    identity: Annotated[PackIdentity, Depends(get_pack_identity)],
    x_active_role: Annotated[str | None, Header()] = None,
) -> Me:
    """The signed-in user; ``active_role`` is null for a user who holds console roles only."""
    roles = identity.roles
    try:
        role = active_role(principal.roles, roles, x_active_role)
    except RoleError as error:
        if x_active_role is not None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail=str(error)) from None
        role = None
    return Me(
        user_id=principal.user_id, display_name=principal.display_name,
        roles=known_roles(principal.roles, roles), active_role=role,
    )


@router.get("/pack")
def pack(identity: Annotated[PackIdentity, Depends(get_pack_identity)]) -> PackInfo:
    """The active pack, from its pack files while it was never compiled."""
    return PackInfo(name=identity.name, display_name=identity.display_name, roles=identity.roles)
