"""Map a principal's roles to the pack role a request runs as (DECISIONS §9).

An account holds roles of the active pack and console roles. A request runs
as one pack role: the one named by the optional ``X-Active-Role`` header,
which the principal must hold, or else its first pack role in
``policies.yaml`` order. A principal without a pack role may not ask
questions.
"""

from collections.abc import Iterable

# Workspace console roles (DECISIONS §15); they grant no data access.
CONSOLE_ROLES = ("pack_reviewer", "admin")


class RoleError(Exception):
    """The principal holds no usable pack role; the request is forbidden."""


def held_pack_roles(held_roles: Iterable[str], pack_roles: list[str]) -> list[str]:
    held = set(held_roles)
    return [role for role in pack_roles if role in held]


def known_roles(held_roles: Iterable[str], pack_roles: list[str]) -> list[str]:
    """The pack roles in policy order, then the console roles; any other role is dropped."""
    held = set(held_roles)
    return [*held_pack_roles(held, pack_roles), *(role for role in CONSOLE_ROLES if role in held)]


def active_role(held_roles: Iterable[str], pack_roles: list[str], requested: str | None) -> str:
    held = held_pack_roles(held_roles, pack_roles)
    if not held:
        raise RoleError("you hold no role of this pack")
    if requested is None:
        return held[0]
    if requested not in held:
        raise RoleError(f"the requested role {requested!r} is not a pack role you hold")
    return requested
