"""The user a request acts as (DECISIONS §9).

Every router reads one ``Principal`` through ``current_principal`` in
``app/api/auth.py``: in individual mode it is the built-in owner, who holds
every pack role and every console role; in team mode it is the signed-in
account of the session cookie. ``user_id`` is what conversations and
``agent_logs`` record. The owner's id is also the id of the first admin when
the instance moves to team mode, so the owner's conversations stay theirs.
"""

from dataclasses import dataclass

from app.auth.roles import CONSOLE_ROLES

# The cookie that carries the random session id of a signed-in account.
SESSION_COOKIE = "fitcher_session"


@dataclass(frozen=True)
class Principal:
    user_id: str
    subject: str
    display_name: str
    roles: tuple[str, ...]


OWNER_ID = "owner"


def owner(pack_roles: list[str]) -> Principal:
    return Principal(user_id=OWNER_ID, subject=OWNER_ID, display_name="Owner", roles=(*pack_roles, *CONSOLE_ROLES))
