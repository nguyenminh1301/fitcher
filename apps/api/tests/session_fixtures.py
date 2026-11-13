"""Signed-in test clients: an account in the test's app state and its session cookie."""

from fastapi.testclient import TestClient

from app.auth import accounts, sessions
from app.auth.principal import SESSION_COOKIE
from app.state.db import shared_state

PASSWORD = "correct horse"


def sign_in(client: TestClient, account_id: str, roles: list[str], email: str | None = None) -> accounts.Account:
    """Create the account unless it exists and put a session cookie for it on ``client``."""
    db = shared_state()
    account = accounts.get(db, account_id) or accounts.create(
        db, email or f"{account_id}@example.com", account_id, PASSWORD, roles, account_id=account_id,
    )
    client.cookies.set(SESSION_COOKIE, sessions.start(db, account.id))
    return account
