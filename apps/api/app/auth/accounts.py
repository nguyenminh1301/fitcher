"""Team-mode accounts kept in the app state (DECISIONS §9).

An account has a unique lower-cased e-mail, a display name, an Argon2id
password hash, a status and the pack and console roles it holds. Passwords are
hashed with argon2-cffi's default parameters, which follow the library's
current recommendation; a stored hash made with older parameters is replaced
on the next successful sign-in. Changing the password or disabling the
account ends its sessions in the same transaction. The last enabled ``admin``
cannot be disabled or lose the role, so an instance always keeps an admin.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
import sqlite3
import uuid

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.state.db import StateDb

ADMIN = "admin"
MIN_PASSWORD_LENGTH = 8

_hasher = PasswordHasher()
# Verified when no account matches, so an unknown e-mail costs as much time as a wrong password.
_DUMMY_HASH = _hasher.hash("no account has this password")


class AccountError(ValueError):
    """The request does not fit the accounts."""


class DuplicateEmail(AccountError):
    pass


class UnknownAccount(AccountError):
    pass


class WeakPassword(AccountError):
    pass


class LastAdmin(AccountError):
    pass


@dataclass(frozen=True)
class Account:
    id: str
    email: str
    display_name: str
    enabled: bool
    roles: tuple[str, ...]


def normalize_email(email: str) -> str:
    value = email.strip().lower()
    local, at, domain = value.partition("@")
    if not at or not local or not domain:
        raise AccountError("enter an e-mail address such as name@example.com")
    return value


def _check_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPassword(f"a password needs at least {MIN_PASSWORD_LENGTH} characters")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _roles(conn: sqlite3.Connection, account_id: str) -> tuple[str, ...]:
    rows = conn.execute("SELECT role FROM account_roles WHERE account_id = ? ORDER BY role", (account_id,))
    return tuple(row[0] for row in rows)


def _account(conn: sqlite3.Connection, row) -> Account:
    account_id, email, display_name, status = row
    return Account(account_id, email, display_name, status == "enabled", _roles(conn, account_id))


_COLUMNS = "id, email, display_name, status"


def get(db: StateDb, account_id: str) -> Account | None:
    conn = db.connection()
    row = conn.execute(f"SELECT {_COLUMNS} FROM accounts WHERE id = ?", (account_id,)).fetchone()
    return None if row is None else _account(conn, row)


def list_all(db: StateDb) -> list[Account]:
    conn = db.connection()
    return [_account(conn, row) for row in conn.execute(f"SELECT {_COLUMNS} FROM accounts ORDER BY email").fetchall()]


def _set_roles(conn: sqlite3.Connection, account_id: str, roles: Iterable[str]) -> None:
    conn.execute("DELETE FROM account_roles WHERE account_id = ?", (account_id,))
    conn.executemany("INSERT INTO account_roles (account_id, role) VALUES (?, ?)",
                     [(account_id, role) for role in sorted(set(roles))])


def create(
    db: StateDb, email: str, display_name: str, password: str | None, roles: Iterable[str],
    account_id: str | None = None,
) -> Account:
    """A new enabled account; ``password`` is None for an account that signs in only through OIDC."""
    email = normalize_email(email)
    if password is not None:
        _check_password(password)
    password_hash = None if password is None else _hasher.hash(password)
    account_id = account_id or uuid.uuid4().hex
    now = _now()
    try:
        with db.write() as conn:
            conn.execute(
                "INSERT INTO accounts (id, email, display_name, password_hash, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 'enabled', ?, ?)",
                (account_id, email, display_name.strip() or email, password_hash, now, now),
            )
            _set_roles(conn, account_id, roles)
    except sqlite3.IntegrityError:
        raise DuplicateEmail("an account with this e-mail already exists") from None
    return get(db, account_id)


def authenticate(db: StateDb, email: str, password: str) -> Account | None:
    """The enabled account with this e-mail and password, else None; the time taken does not tell which failed."""
    try:
        email = normalize_email(email)
    except AccountError:
        email = ""
    row = db.connection().execute(
        "SELECT id, password_hash, status FROM accounts WHERE email = ?", (email,)
    ).fetchone()
    stored = row[1] if row is not None and row[1] else _DUMMY_HASH
    try:
        _hasher.verify(stored, password)
    except (VerificationError, InvalidHashError):
        return None
    if row is None or not row[1] or row[2] != "enabled":
        return None
    if _hasher.check_needs_rehash(stored):
        with db.write() as conn:
            conn.execute("UPDATE accounts SET password_hash = ? WHERE id = ?", (_hasher.hash(password), row[0]))
    return get(db, row[0])


def _require(conn: sqlite3.Connection, account_id: str) -> None:
    if conn.execute("SELECT 1 FROM accounts WHERE id = ?", (account_id,)).fetchone() is None:
        raise UnknownAccount("account not found")


def set_password(db: StateDb, account_id: str, password: str) -> None:
    """Replace the password and end every session of the account."""
    _check_password(password)
    password_hash = _hasher.hash(password)
    with db.write() as conn:
        _require(conn, account_id)
        conn.execute("UPDATE accounts SET password_hash = ?, updated_at = ? WHERE id = ?",
                     (password_hash, _now(), account_id))
        conn.execute("DELETE FROM sessions WHERE account_id = ?", (account_id,))


def _enabled_admins(conn: sqlite3.Connection) -> int:
    return conn.execute(
        "SELECT count(*) FROM accounts a JOIN account_roles r ON r.account_id = a.id "
        "WHERE a.status = 'enabled' AND r.role = ?", (ADMIN,),
    ).fetchone()[0]


def update(
    db: StateDb, account_id: str, *, display_name: str | None = None, roles: Iterable[str] | None = None,
    enabled: bool | None = None,
) -> Account:
    """Change the name, roles or status; disabling ends the account's sessions."""
    roles = None if roles is None else list(roles)
    with db.write() as conn:
        _require(conn, account_id)
        admins_before = _enabled_admins(conn)
        if display_name is not None:
            conn.execute("UPDATE accounts SET display_name = ? WHERE id = ?", (display_name.strip(), account_id))
        if roles is not None:
            _set_roles(conn, account_id, roles)
        if enabled is not None:
            conn.execute("UPDATE accounts SET status = ? WHERE id = ?", ("enabled" if enabled else "disabled", account_id))
            if not enabled:
                conn.execute("DELETE FROM sessions WHERE account_id = ?", (account_id,))
        if admins_before and not _enabled_admins(conn):
            # Raising inside the transaction rolls back every change above.
            raise LastAdmin("the last enabled admin cannot be disabled or lose the admin role")
        conn.execute("UPDATE accounts SET updated_at = ? WHERE id = ?", (_now(), account_id))
    return get(db, account_id)
