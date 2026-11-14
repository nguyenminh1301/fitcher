"""First-run setup: the state of each step and whether setup is complete.

Only the steps that have an implementation are listed; a later phase adds its
step id to ``STEPS``. A step is ``pending`` until the user answers it
(``done``) or leaves it (``skipped``).
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from app.auth import accounts
from app.auth.principal import OWNER_ID
from app.state.db import StateDb
from app.state.settings import INSTANCE_MODES, Settings

STEPS = ("mode", "models", "data")


class SetupError(ValueError):
    """The request does not fit the setup state."""


class UnknownStep(SetupError):
    pass


@dataclass(frozen=True)
class Step:
    id: str
    state: str


@dataclass(frozen=True)
class Status:
    mode: str | None
    steps: list[Step]
    complete: bool


def _mark(db: StateDb, step: str, state: str) -> None:
    with db.write() as conn:
        conn.execute(
            "INSERT INTO setup_steps (id, state, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET state = excluded.state, updated_at = excluded.updated_at",
            (step, state, datetime.now(UTC).isoformat()),
        )


def status(db: StateDb) -> Status:
    states = dict(db.connection().execute("SELECT id, state FROM setup_steps").fetchall())
    settings = Settings(db)
    return Status(
        mode=settings.get("instance", "mode"),
        steps=[Step(step, states.get(step, "pending")) for step in STEPS],
        complete=settings.get("setup", "complete"),
    )


@dataclass(frozen=True)
class FirstAdmin:
    email: str
    display_name: str
    password: str


class FirstAdminNeeded(SetupError):
    pass


class TooManyAccounts(SetupError):
    pass


def _enabled_accounts(db: StateDb) -> list[accounts.Account]:
    return [account for account in accounts.list_all(db) if account.enabled]


def set_mode(
    db: StateDb, mode: str, first_admin: FirstAdmin | None = None, pack_roles: list[str] | tuple[str, ...] = (),
) -> accounts.Account | None:
    """Choose who uses the instance (DECISIONS §9); returns the first admin when this call created it.

    Moving to team mode without an enabled admin creates one from ``first_admin`` with the owner's id, so
    the owner's conversations, groups and feedback, recorded under that id, become the admin's without a
    rewrite. The first admin holds ``admin`` and the pack roles the owner held. Moving to individual mode
    is refused while more than one account is enabled.
    """
    if mode not in INSTANCE_MODES:
        raise SetupError(f"mode must be one of {', '.join(INSTANCE_MODES)}")
    created = None
    if mode == "team" and not any(accounts.ADMIN in account.roles for account in _enabled_accounts(db)):
        if first_admin is None:
            raise FirstAdminNeeded("team mode needs its first admin: an e-mail, a name and a password")
        account_id = OWNER_ID if accounts.get(db, OWNER_ID) is None else None
        created = accounts.create(db, first_admin.email, first_admin.display_name, first_admin.password,
                                  [accounts.ADMIN, *pack_roles], account_id=account_id)
    if mode == "individual" and len(_enabled_accounts(db)) > 1:
        raise TooManyAccounts("individual mode needs at most one enabled account; disable the others first")
    Settings(db).set("instance", "mode", mode)
    _mark(db, "mode", "done")
    return created


def mark_done(db: StateDb, step: str) -> None:
    if step not in STEPS:
        raise UnknownStep(f"unknown setup step {step!r}")
    _mark(db, step, "done")


def skip(db: StateDb, step: str) -> None:
    if step not in STEPS:
        raise UnknownStep(f"unknown setup step {step!r}")
    _mark(db, step, "skipped")


def complete(db: StateDb) -> None:
    pending = [s.id for s in status(db).steps if s.state == "pending"]
    if pending:
        raise SetupError(f"answer or skip these steps first: {', '.join(pending)}")
    Settings(db).set("setup", "complete", True)
