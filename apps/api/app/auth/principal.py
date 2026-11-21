"""The user a request acts as (DECISIONS §9).

Every router reads one ``Principal`` through ``current_principal`` in
``app/api/auth.py``: the built-in owner of this personal app, who holds every
pack role and every console role. ``user_id`` is what conversations and
``agent_logs`` record.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Principal:
    user_id: str
    subject: str
    display_name: str
    roles: tuple[str, ...]


OWNER_ID = "owner"


def owner(pack_roles: list[str]) -> Principal:
    return Principal(user_id=OWNER_ID, subject=OWNER_ID, display_name="Owner", roles=tuple(pack_roles))
