"""Secrets encrypted with the instance key (DECISIONS §9).

The key is ``FITCHER_SECRET_KEY`` (base64, 32 bytes) or a key generated on
first use in ``<FITCHER_DATA_DIR>/secret.key`` with mode 0600. A secret is
stored as a random nonce plus AES-256-GCM ciphertext whose associated data is
the secret's name, so a ciphertext copied to another name does not decrypt.

``SecretVault`` can store, check and delete a secret and report its last four
characters; it has no method that returns a value. Code that needs the value
(the model gateway) receives a ``SecretReader`` from ``SecretVault.reader()``;
no API handler takes one.
"""

import base64
import binascii
from datetime import UTC, datetime
import os
from pathlib import Path
import secrets as random

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.state.db import StateDb

KEY_ENV = "FITCHER_SECRET_KEY"
KEY_FILE = "secret.key"
KEY_BYTES = 32


class SecretError(RuntimeError):
    """The instance key is unusable, or a secret cannot be stored or read."""


def _decode(value: str, source: str) -> bytes:
    try:
        key = base64.b64decode(value.strip(), validate=True)
    except (binascii.Error, ValueError):
        raise SecretError(f"{source} must be base64 of {KEY_BYTES} bytes") from None
    if len(key) != KEY_BYTES:
        raise SecretError(f"{source} must be base64 of {KEY_BYTES} bytes, got {len(key)}")
    return key


def load_key(data_dir: Path, env: dict[str, str] | None = None, db: StateDb | None = None) -> bytes:
    """The instance key; generated into ``secret.key`` only when no secret exists yet."""
    env = os.environ if env is None else env
    if env.get(KEY_ENV):
        return _decode(env[KEY_ENV], KEY_ENV)
    path = Path(data_dir) / KEY_FILE
    if path.exists():
        return _decode(path.read_text(encoding="ascii"), str(path))
    if db is not None and db.connection().execute("SELECT 1 FROM secrets LIMIT 1").fetchone():
        raise SecretError(
            f"{path} is missing but secrets are stored: restore it from a backup or set {KEY_ENV}; "
            "a new key would make them unreadable"
        )
    key = random.token_bytes(KEY_BYTES)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as handle:
        handle.write(base64.b64encode(key).decode("ascii"))
    return key


class SecretReader:
    """The one way to read a secret value; handed only to code that calls a provider."""

    def __init__(self, db: StateDb, key: bytes):
        self._db = db
        self._aead = AESGCM(key)

    def get(self, name: str) -> str:
        row = self._db.connection().execute("SELECT nonce, ciphertext FROM secrets WHERE name = ?", (name,)).fetchone()
        if row is None:
            raise SecretError(f"secret {name!r} is not set")
        try:
            return self._aead.decrypt(row[0], row[1], name.encode("utf-8")).decode("utf-8")
        except InvalidTag:
            raise SecretError(
                f"secret {name!r} cannot be decrypted: the instance key does not match the one that stored it"
            ) from None


class SecretVault:
    def __init__(self, db: StateDb, key: bytes):
        if len(key) != KEY_BYTES:
            raise SecretError(f"the instance key must be {KEY_BYTES} bytes")
        self._db = db
        self._key = key
        self._aead = AESGCM(key)

    def set(self, name: str, value: str) -> None:
        if not value:
            raise SecretError("a secret cannot be empty")
        nonce = random.token_bytes(12)
        ciphertext = self._aead.encrypt(nonce, value.encode("utf-8"), name.encode("utf-8"))
        with self._db.write() as conn:
            conn.execute(
                "INSERT INTO secrets (name, nonce, ciphertext, last_four, updated_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET nonce = excluded.nonce, ciphertext = excluded.ciphertext, "
                "last_four = excluded.last_four, updated_at = excluded.updated_at",
                (name, nonce, ciphertext, value[-4:], datetime.now(UTC).isoformat()),
            )

    def has(self, name: str) -> bool:
        return self._db.connection().execute("SELECT 1 FROM secrets WHERE name = ?", (name,)).fetchone() is not None

    def last_four(self, name: str) -> str | None:
        row = self._db.connection().execute("SELECT last_four FROM secrets WHERE name = ?", (name,)).fetchone()
        return row[0] if row else None

    def delete(self, name: str) -> None:
        with self._db.write() as conn:
            conn.execute("DELETE FROM secrets WHERE name = ?", (name,))

    def reader(self) -> SecretReader:
        return SecretReader(self._db, self._key)
