"""A migrated app state in a temporary directory, with a vault under a fixed test key."""

from pathlib import Path

from app.state import migrate
from app.state.db import StateDb
from app.state.secrets import SecretVault

TEST_KEY = bytes([3]) * 32


def new_state(directory: Path) -> tuple[StateDb, SecretVault]:
    db = StateDb(directory / "app.db")
    migrate.apply_pending(db)
    return db, SecretVault(db, TEST_KEY)
