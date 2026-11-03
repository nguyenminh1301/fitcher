"""Map a token's realm roles to the pack role a request runs as (DECISIONS §9).

Keycloak realm roles equal the active pack's policy roles plus the console
roles. A request runs as one pack role: the one named by the optional
``X-Active-Role`` header, which the token must hold, or else the token's
first pack role in ``policies.yaml`` order. A token without a pack role may
not ask questions.
"""

from collections.abc import Iterable

# Workspace console roles (DECISIONS §15); they grant no data access.
CONSOLE_ROLES = ("pack_reviewer", "admin")


class RoleError(Exception):
    """The token holds no usable pack role; the request is forbidden."""


def held_pack_roles(token_roles: Iterable[str], pack_roles: list[str]) -> list[str]:
    held = set(token_roles)
    return [role for role in pack_roles if role in held]


def known_roles(token_roles: Iterable[str], pack_roles: list[str]) -> list[str]:
    """The token's pack roles in policy order, then its console roles; Keycloak's own roles are dropped."""
    held = set(token_roles)
    return [*held_pack_roles(held, pack_roles), *(role for role in CONSOLE_ROLES if role in held)]


def active_role(token_roles: Iterable[str], pack_roles: list[str], requested: str | None) -> str:
    held = held_pack_roles(token_roles, pack_roles)
    if not held:
        raise RoleError("the token holds no role of this pack")
    if requested is None:
        return held[0]
    if requested not in held:
        raise RoleError(f"the requested role {requested!r} is not a pack role of this token")
    return requested
