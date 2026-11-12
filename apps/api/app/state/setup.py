"""First-run setup: the state of each step and whether setup is complete.

Only the steps that have an implementation are listed; a later phase adds its
step id to ``STEPS``. A step is ``pending`` until the user answers it
(``done``) or leaves it (``skipped``).
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from app.state.db import StateDb
from app.state.settings import INSTANCE_MODES, Settings

STEPS = ("mode",)


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


def set_mode(db: StateDb, mode: str) -> None:
    if mode not in INSTANCE_MODES:
        raise SetupError(f"mode must be one of {', '.join(INSTANCE_MODES)}")
    Settings(db).set("instance", "mode", mode)
    _mark(db, "mode", "done")


def skip(db: StateDb, step: str) -> None:
    if step not in STEPS:
        raise UnknownStep(f"unknown setup step {step!r}")
    _mark(db, step, "skipped")


def complete(db: StateDb) -> None:
    pending = [s.id for s in status(db).steps if s.state == "pending"]
    if pending:
        raise SetupError(f"answer or skip these steps first: {', '.join(pending)}")
    Settings(db).set("setup", "complete", True)
