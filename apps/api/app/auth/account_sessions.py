"""Server-side session of each signed-in account, and the sign-in throttle (DECISIONS §9).

A session id is 32 random bytes sent to the browser in the session cookie;
the app state keeps only its SHA-256 with the account and its creation and
last-use times. A session ends after 12 hours without a request, 30 days after
it started, on sign-out, on a password change and when the account is
disabled. The principal is read from the account on every request, so a role
change or a disable reaches the user's next request.

Sign-in attempts are counted per e-mail and per client address over a
15-minute window; an attempt is counted before its password is checked and
only its own count is released when it succeeds. Once a key reaches its
limit, further attempts are refused until the counted failure that reached it
leaves the window, whether or not the account exists.
"""

from collections.abc import Callable, Iterable
import hashlib
import math
import secrets
import time

from app.auth import accounts
from app.auth.principal import Principal
from app.state.db import StateDb

IDLE_SECONDS = 12 * 3600
LIFETIME_SECONDS = 30 * 24 * 3600
# last_used_at is written at most this often, so reads do not each take the write lock.
TOUCH_SECONDS = 60

Clock = Callable[[], float]


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def start(db: StateDb, account_id: str, clock: Clock = time.time) -> str:
    """A new session for the account; returns the session id the cookie carries."""
    token = secrets.token_urlsafe(32)
    now = clock()
    with db.write() as conn:
        conn.execute("INSERT INTO account_sessions (id_hash, account_id, created_at, last_used_at) VALUES (?, ?, ?, ?)",
                     (_hash(token), account_id, now, now))
    return token


def end(db: StateDb, token: str) -> None:
    with db.write() as conn:
        conn.execute("DELETE FROM account_sessions WHERE id_hash = ?", (_hash(token),))


def principal_for(db: StateDb, token: str, clock: Clock = time.time) -> Principal | None:
    """The enabled account of a live session, else None; an expired session is deleted."""
    if not token:
        return None
    id_hash = _hash(token)
    row = db.connection().execute(
        "SELECT account_id, created_at, last_used_at FROM account_sessions WHERE id_hash = ?", (id_hash,)
    ).fetchone()
    if row is None:
        return None
    account_id, created_at, last_used_at = row
    now = clock()
    if now - last_used_at > IDLE_SECONDS or now - created_at > LIFETIME_SECONDS:
        end(db, token)
        return None
    account = accounts.get(db, account_id)
    if account is None or not account.enabled:
        return None
    if now - last_used_at >= TOUCH_SECONDS:
        with db.write() as conn:
            conn.execute("UPDATE account_sessions SET last_used_at = ? WHERE id_hash = ?", (now, id_hash))
    return Principal(user_id=account.id, subject=account.id, display_name=account.display_name, roles=account.roles)


WINDOW_SECONDS = 15 * 60
# Failures a key may collect inside the window; an address is shared by everyone behind one NAT.
LIMITS = {"email": 5, "address": 20}


def email_key(email: str) -> str:
    return f"email:{email.strip().lower()}"


def address_key(address: str) -> str:
    return f"address:{address}"


class SignInThrottle:
    """Counts each sign-in attempt before its password is checked, so parallel attempts cannot pass the limit."""

    def __init__(self, db: StateDb, clock: Clock = time.time):
        self._db = db
        self._clock = clock

    def reserve(self, keys: Iterable[str]) -> tuple[int, list[int]]:
        """Count one attempt for each key, or refuse it.

        Returns ``(0, rows)`` when the attempt may go ahead, its rows counted as failures until
        ``succeeded`` releases them, or ``(seconds, [])`` until an attempt is accepted again.
        """
        keys = list(keys)
        now = self._clock()
        with self._db.write() as conn:
            conn.execute("DELETE FROM sign_in_failures WHERE failed_at <= ?", (now - WINDOW_SECONDS,))
            wait = 0.0
            for key in keys:
                limit = LIMITS[key.partition(":")[0]]
                times = [row[0] for row in conn.execute(
                    "SELECT failed_at FROM sign_in_failures WHERE key = ? ORDER BY failed_at DESC", (key,),
                )]
                if len(times) >= limit:
                    # Accepted again when the failure that reached the limit leaves the window.
                    wait = max(wait, times[limit - 1] + WINDOW_SECONDS - now)
            if wait > 0:
                return math.ceil(wait), []
            rows = [conn.execute("INSERT INTO sign_in_failures (key, failed_at) VALUES (?, ?)", (key, now)).lastrowid
                    for key in keys]
        return 0, rows

    def succeeded(self, rows: list[int]) -> None:
        """Release a successful attempt's own rows.

        Earlier rows of the same e-mail stay until they leave the window: some may belong to attempts still
        being checked, which must keep counting.
        """
        with self._db.write() as conn:
            conn.executemany("DELETE FROM sign_in_failures WHERE rowid = ?", [(row,) for row in rows])
