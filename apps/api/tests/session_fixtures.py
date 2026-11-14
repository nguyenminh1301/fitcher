"""Signed-in test clients: an account in the test's app state and its session cookie."""

from collections.abc import Iterable, Iterator, Mapping

from fastapi.testclient import TestClient

from app.api import runtime
from app.auth import account_sessions, accounts
from app.auth.principal import SESSION_COOKIE
from app.main import app
from app.state.db import shared_state

PASSWORD = "correct horse"


def sign_in(client: TestClient, account_id: str, roles: list[str], email: str | None = None) -> accounts.Account:
    """Create the account unless it exists and put a session cookie for it on ``client``."""
    db = shared_state()
    account = accounts.get(db, account_id) or accounts.create(
        db, email or f"{account_id}@example.com", account_id, PASSWORD, roles, account_id=account_id,
    )
    client.cookies.set(SESSION_COOKIE, account_sessions.start(db, account.id))
    return account


class SessionHeaders(Mapping[str, str]):
    """A ``Cookie`` header carrying a session of one account, made in the current test's app state when read.

    Module-level constants are built before a test's app state exists, so the account and its session are
    created only when a request reads the header. The account has no password, which keeps hashing out of
    the tests that only need a signed-in user.
    """

    def __init__(self, roles: Iterable[str] = ("viewer",), user_id: str = "lab.viewer", display_name: str | None = None):
        self._roles = list(roles)
        self._user_id = user_id
        self._display_name = display_name or user_id

    def _cookie(self) -> str:
        # The app state the app reads in this test: a test may override it with its own.
        db = app.dependency_overrides.get(runtime.get_state_db, shared_state)()
        if accounts.get(db, self._user_id) is None:
            accounts.create(db, f"{self._user_id}@example.com", self._display_name, None, self._roles, account_id=self._user_id)
        else:
            # The same test user may sign in with other roles in one test; set them as given, without the
            # last-admin rule, which guards real accounts.
            with db.write() as conn:
                conn.execute("DELETE FROM account_roles WHERE account_id = ?", (self._user_id,))
                conn.executemany("INSERT INTO account_roles (account_id, role) VALUES (?, ?)",
                                 [(self._user_id, role) for role in set(self._roles)])
        return f"{SESSION_COOKIE}={account_sessions.start(db, self._user_id)}"

    def __getitem__(self, key: str) -> str:
        if key != "Cookie":
            raise KeyError(key)
        return self._cookie()

    def __iter__(self) -> Iterator[str]:
        return iter(["Cookie"])

    def __len__(self) -> int:
        return 1


# A cookie for a session the api does not know, as an expired or forged one looks.
UNKNOWN_SESSION = {"Cookie": f"{SESSION_COOKIE}=not-a-session"}
