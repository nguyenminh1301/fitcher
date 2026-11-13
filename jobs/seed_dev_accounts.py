"""Create the development accounts of ``infra/dev/accounts.yaml`` in team mode.

Run with ``docker compose run --rm jobs python -m jobs.seed_dev_accounts``.
Each account gets the password ``DEV_ACCOUNT_PASSWORD`` from the local
``.env`` (at least 8 characters, never printed), the roles of the file and the
enabled status; a second run resets them. The account ids are the usernames
the development users had before, so their conversations and run logs stay
theirs. The instance is put in team mode. This is a development tool: the
released image has no development accounts.
"""

from collections.abc import Mapping
from dataclasses import dataclass
import os
from pathlib import Path
import sys

import yaml

from app.auth import accounts
from app.state import setup
from app.state.db import StateDb, data_dir
from app.state.migrate import apply_pending

ACCOUNTS_FILE = Path(__file__).resolve().parents[1] / "infra" / "dev" / "accounts.yaml"


@dataclass(frozen=True)
class DevAccount:
    id: str
    email: str
    display_name: str
    roles: list[str]


def read_accounts(path: Path = ACCOUNTS_FILE) -> list[DevAccount]:
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [DevAccount(item["id"], item["email"], item["display_name"], list(item["roles"])) for item in document["accounts"]]


def seed(db: StateDb, wanted: list[DevAccount], password: str) -> int:
    """Create or reset every account, then put the instance in team mode; returns the number of accounts.

    Admin accounts come first, so an enabled admin exists before another account can lose the role: the
    last-admin rule would otherwise stop a reset of an instance whose only admin is a changed account.
    """
    for account in sorted(wanted, key=lambda item: accounts.ADMIN not in item.roles):
        if accounts.get(db, account.id) is None:
            accounts.create(db, account.email, account.display_name, password, account.roles, account_id=account.id)
        else:
            accounts.set_password(db, account.id, password)
            accounts.update(db, account.id, display_name=account.display_name, roles=account.roles, enabled=True)
    setup.set_mode(db, "team")
    print(f"{len(wanted)} development accounts ready; the instance is in team mode")
    return len(wanted)


def main(env: Mapping[str, str] | None = None) -> int:
    env = os.environ if env is None else env
    password = env.get("DEV_ACCOUNT_PASSWORD", "")
    if len(password) < accounts.MIN_PASSWORD_LENGTH:
        print(f"DEV_ACCOUNT_PASSWORD must be set to at least {accounts.MIN_PASSWORD_LENGTH} characters", file=sys.stderr)
        return 1
    db = StateDb(data_dir(dict(env)) / "app.db")
    apply_pending(db)
    try:
        seed(db, read_accounts(), password)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
