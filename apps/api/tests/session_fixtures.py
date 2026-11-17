"""Request headers for the owner of this personal app, acting under one pack role.

fitcher has no accounts (DECISIONS §9): every request is the owner, who holds every pack role. Tests that
exercise a pack role send it as ``X-Active-Role``; console roles need no header because the owner holds them.
"""

from collections.abc import Iterable, Iterator, Mapping

from app.auth.roles import CONSOLE_ROLES


class SessionHeaders(Mapping[str, str]):
    """The ``X-Active-Role`` header of the first pack role in ``roles``, or no header when it names none."""

    def __init__(self, roles: Iterable[str] = (), user_id: str = "owner", display_name: str | None = None):
        self._role = next((role for role in roles if role not in CONSOLE_ROLES), None)

    def __getitem__(self, key: str) -> str:
        if key != "X-Active-Role" or self._role is None:
            raise KeyError(key)
        return self._role

    def __iter__(self) -> Iterator[str]:
        return iter(["X-Active-Role"] if self._role is not None else [])

    def __len__(self) -> int:
        return 1 if self._role is not None else 0
