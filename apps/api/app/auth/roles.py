"""The pack role a request runs as (DECISIONS §9).

fitcher has one owner, who holds every role of the pack's ``policies.yaml``. A
request runs as the first of them in policy order; a pack without a role may
not be asked questions.
"""

from collections.abc import Iterable


class RoleError(Exception):
    """The principal holds no usable pack role; the request is forbidden."""


def held_pack_roles(held_roles: Iterable[str], pack_roles: list[str]) -> list[str]:
    held = set(held_roles)
    return [role for role in pack_roles if role in held]


def active_role(held_roles: Iterable[str], pack_roles: list[str]) -> str:
    held = held_pack_roles(held_roles, pack_roles)
    if not held:
        raise RoleError("you hold no role of this pack")
    return held[0]
