"""The optional owner password of this personal app (DECISIONS §9).

Without a password the address checks of ``app/auth/origin.py`` are the only gate, so the instance answers this
computer alone. Once the owner sets a password, every request except the public paths needs a signed-in
session, wherever it comes from; an instance reachable through a ``FITCHER_ALLOWED_HOSTS`` name refuses those
requests until a password is set, and keeps its password while it stays reachable.

The password is stored as an Argon2id hash. A session id is 32 random bytes sent in an ``HttpOnly``,
``SameSite=Strict`` cookie; the app state keeps only its SHA-256 with its creation and last-use times. A
session ends after 12 hours without a request, 30 days after it started, on sign-out and whenever the password
changes or is removed. Sign-in attempts are counted per client over a 15-minute window before the password is
checked; a successful attempt releases only its own count. The owner at this computer is one client of its own, so
wrong passwords sent through the published port from anywhere else never lock them out; the other clients also
share a global limit, a backstop against a guesser that spreads its attempts over many addresses.
"""

from collections.abc import Callable
from datetime import UTC, datetime
import hashlib
import math
import secrets
import time

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.state.db import StateDb

SESSION_COOKIE = "fitcher_session"
# An instance listed in FITCHER_ALLOWED_HOSTS answers the internet with this password alone; a password set
# before the minimum was raised still signs in.
MIN_LENGTH = 12
IDLE_SECONDS = 12 * 3600
LIFETIME_SECONDS = 30 * 24 * 3600
# last_used_at is written at most this often, so reads do not each take the write lock.
TOUCH_SECONDS = 60
WINDOW_SECONDS = 15 * 60
FAILURE_LIMIT = 10
GLOBAL_FAILURE_LIMIT = 100
LOCAL_KEY = "local"

Clock = Callable[[], float]
_hasher = PasswordHasher()


class PasswordError(ValueError):
    """The password change was refused."""


class WeakPassword(PasswordError):
    pass


class WrongPassword(PasswordError):
    pass


def password_set(db: StateDb) -> bool:
    return db.connection().execute("SELECT 1 FROM owner_password").fetchone() is not None


def verify(db: StateDb, password: str) -> bool:
    row = db.connection().execute("SELECT password_hash FROM owner_password").fetchone()
    if row is None:
        return False
    try:
        return _hasher.verify(row[0], password)
    except (VerificationError, InvalidHashError):
        return False


def _check_current(db: StateDb, current: str | None) -> None:
    if password_set(db) and not verify(db, current or ""):
        raise WrongPassword("the current password is not right")


def set_password(db: StateDb, password: str, current: str | None = None) -> None:
    """Set or change the password; a change needs the current one. Every existing session ends."""
    if len(password) < MIN_LENGTH:
        raise WeakPassword(f"the password needs at least {MIN_LENGTH} characters")
    _check_current(db, current)
    hashed = _hasher.hash(password)
    with db.write() as conn:
        conn.execute(
            "INSERT INTO owner_password (id, password_hash, updated_at) VALUES (1, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET password_hash = excluded.password_hash, updated_at = excluded.updated_at",
            (hashed, datetime.now(UTC).isoformat()),
        )
        conn.execute("DELETE FROM owner_sessions")


def remove_password(db: StateDb, current: str) -> None:
    """Remove the password; it needs the current one. Every session ends."""
    _check_current(db, current)
    with db.write() as conn:
        conn.execute("DELETE FROM owner_password")
        conn.execute("DELETE FROM owner_sessions")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def start_session(db: StateDb, clock: Clock = time.time) -> str:
    """A new session; returns the session id the cookie carries."""
    token = secrets.token_urlsafe(32)
    now = clock()
    with db.write() as conn:
        conn.execute("INSERT INTO owner_sessions (id_hash, created_at, last_used_at) VALUES (?, ?, ?)",
                     (_hash(token), now, now))
    return token


def end_session(db: StateDb, token: str) -> None:
    with db.write() as conn:
        conn.execute("DELETE FROM owner_sessions WHERE id_hash = ?", (_hash(token),))


def session_valid(db: StateDb, token: str | None, clock: Clock = time.time) -> bool:
    """Whether ``token`` is a live session; an expired one is deleted."""
    if not token:
        return False
    id_hash = _hash(token)
    row = db.connection().execute(
        "SELECT created_at, last_used_at FROM owner_sessions WHERE id_hash = ?", (id_hash,)
    ).fetchone()
    if row is None:
        return False
    created_at, last_used_at = row
    now = clock()
    if now - last_used_at > IDLE_SECONDS or now - created_at > LIFETIME_SECONDS:
        end_session(db, token)
        return False
    if now - last_used_at >= TOUCH_SECONDS:
        with db.write() as conn:
            conn.execute("UPDATE owner_sessions SET last_used_at = ? WHERE id_hash = ?", (now, id_hash))
    return True


class SignInThrottle:
    """Counts each sign-in attempt of a client before its password is checked."""

    def __init__(self, db: StateDb, clock: Clock = time.time):
        self._db = db
        self._clock = clock

    def reserve(self, address: str | None) -> tuple[int, list[int]]:
        """``(0, rows)`` when the attempt may go ahead, or ``(seconds, [])`` until an attempt is accepted again.

        ``address`` is the client's address, or None for the owner at this computer, whose attempts count apart
        and are not held by the global limit.
        """
        key = LOCAL_KEY if address is None else f"address:{address}"
        now = self._clock()
        with self._db.write() as conn:
            conn.execute("DELETE FROM sign_in_failures WHERE failed_at <= ?", (now - WINDOW_SECONDS,))
            limits = [(FAILURE_LIMIT, [row[0] for row in conn.execute(
                "SELECT failed_at FROM sign_in_failures WHERE key = ? ORDER BY failed_at DESC", (key,))])]
            if address is not None:
                limits.append((GLOBAL_FAILURE_LIMIT, [row[0] for row in conn.execute(
                    "SELECT failed_at FROM sign_in_failures WHERE key != ? ORDER BY failed_at DESC", (LOCAL_KEY,))]))
            # Accepted again when the failure that reached a limit leaves the window.
            waits = [math.ceil(times[limit - 1] + WINDOW_SECONDS - now) for limit, times in limits if len(times) >= limit]
            if waits:
                return max(waits), []
            row = conn.execute("INSERT INTO sign_in_failures (key, failed_at) VALUES (?, ?)", (key, now)).lastrowid
        return 0, [row]

    def succeeded(self, rows: list[int]) -> None:
        with self._db.write() as conn:
            conn.executemany("DELETE FROM sign_in_failures WHERE rowid = ?", [(row,) for row in rows])
