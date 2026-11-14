import base64
import os
import stat

import pytest

from app.state import migrate
from app.state.db import StateDb
from app.state.secrets import SecretError, SecretVault, load_key


@pytest.fixture
def db(tmp_path):
    db = StateDb(tmp_path / "app.db")
    migrate.apply_pending(db)
    return db


def key_env(byte=1):
    return {"FITCHER_SECRET_KEY": base64.b64encode(bytes([byte]) * 32).decode()}


def test_key_is_generated_once_with_owner_only_mode(tmp_path):
    first = load_key(tmp_path, {})
    path = tmp_path / "secret.key"
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert load_key(tmp_path, {}) == first
    assert len(first) == 32


def test_key_from_environment_wins_and_writes_no_file(tmp_path):
    assert load_key(tmp_path, key_env(7)) == bytes([7]) * 32
    assert not (tmp_path / "secret.key").exists()


@pytest.mark.parametrize("value", ["not base64 !!", base64.b64encode(b"short").decode()])
def test_malformed_environment_key_is_refused(tmp_path, value):
    with pytest.raises(SecretError, match="FITCHER_SECRET_KEY"):
        load_key(tmp_path, {"FITCHER_SECRET_KEY": value})


def test_missing_key_file_is_not_replaced_when_secrets_exist(tmp_path, db):
    vault = SecretVault(db, load_key(tmp_path, {}))
    vault.set("openai", "sk-abcdef1234")
    (tmp_path / "secret.key").unlink()
    with pytest.raises(SecretError, match="secret.key"):
        load_key(tmp_path, {}, db)


def test_set_has_last_four_and_delete(db):
    vault = SecretVault(db, bytes([1]) * 32)
    assert not vault.has("openai")
    vault.set("openai", "sk-abcdef1234")
    assert vault.has("openai")
    assert vault.last_four("openai") == "1234"
    vault.delete("openai")
    assert not vault.has("openai")
    assert vault.last_four("openai") is None


def test_stored_bytes_do_not_contain_the_plaintext(db, tmp_path):
    SecretVault(db, bytes([1]) * 32).set("openai", "sk-very-secret-value-1234")
    db.connection().execute("PRAGMA wal_checkpoint(TRUNCATE)")
    assert b"very-secret" not in (tmp_path / "app.db").read_bytes()
    assert b"very-secret" not in b"".join(p.read_bytes() for p in tmp_path.glob("app.db-*"))


def test_reader_returns_the_value_after_a_restart(db):
    SecretVault(db, bytes([1]) * 32).set("openai", "sk-abcdef1234")
    assert SecretVault(db, bytes([1]) * 32).reader().get("openai") == "sk-abcdef1234"


def test_wrong_key_fails_loudly(db):
    SecretVault(db, bytes([1]) * 32).set("openai", "sk-abcdef1234")
    with pytest.raises(SecretError, match="key"):
        SecretVault(db, bytes([2]) * 32).reader().get("openai")


def test_missing_secret_is_an_error_not_an_empty_string(db):
    with pytest.raises(SecretError, match="not set"):
        SecretVault(db, bytes([1]) * 32).reader().get("openai")


def test_ciphertext_is_bound_to_the_secret_name(db):
    vault = SecretVault(db, bytes([1]) * 32)
    vault.set("a", "value-1111")
    vault.set("b", "value-2222")
    with db.write() as conn:
        conn.execute("UPDATE secrets SET ciphertext = (SELECT ciphertext FROM secrets WHERE name='a'), "
                     "nonce = (SELECT nonce FROM secrets WHERE name='a') WHERE name='b'")
    with pytest.raises(SecretError):
        vault.reader().get("b")


def test_vault_has_no_method_that_returns_a_secret():
    assert not hasattr(SecretVault, "get") and not hasattr(SecretVault, "reveal")


def test_empty_secret_is_refused(db):
    with pytest.raises(SecretError):
        SecretVault(db, bytes([1]) * 32).set("openai", "")


def test_a_derived_key_is_stable_distinct_per_purpose_and_never_the_instance_key():
    from app.state.secrets import derive_key

    key = bytes([9]) * 32
    first = derive_key(key, "clickhouse named collections")

    assert first == derive_key(key, "clickhouse named collections")
    assert len(first) == 32 and first != key
    assert first != derive_key(key, "another purpose")
    assert first != derive_key(bytes([8]) * 32, "clickhouse named collections")
