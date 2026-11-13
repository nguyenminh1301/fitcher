"""The user a request acts as (DECISIONS §9).

Every router reads one ``Principal`` through ``current_principal`` in
``app/api/auth.py``: in team mode it is the signed-in account of the session
cookie. ``user_id`` is what conversations and ``agent_logs`` record.
"""

from dataclasses import dataclass

# The cookie that carries the random session id of a signed-in account.
SESSION_COOKIE = "fitcher_session"


@dataclass(frozen=True)
class Principal:
    user_id: str
    subject: str
    display_name: str
    roles: tuple[str, ...]
