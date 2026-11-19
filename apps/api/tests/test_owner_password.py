"""The owner password: setting, changing and removing it, signing in, and the sign-in throttle."""

import pytest

from app.auth import owner
from app.state import migrate
from app.state.db import StateDb

PASSWORD = "correct horse battery"


@pytest.fixture
def db(tmp_path):
    db = StateDb(tmp_path / "app.db")
    migrate.apply_pending(db)
    return db


def test_a_new_instance_has_no_password(db):
    assert owner.password_set(db) is False
    assert owner.verify(db, "anything") is False


def test_a_password_is_stored_as_an_argon2id_hash_and_verified(db):
    owner.set_password(db, PASSWORD)

    stored = db.connection().execute("SELECT password_hash FROM owner_password").fetchone()[0]
    assert stored.startswith("$argon2id$") and PASSWORD not in stored
    assert owner.password_set(db) and owner.verify(db, PASSWORD) and not owner.verify(db, "wrong password")


def test_a_short_password_is_refused(db):
    with pytest.raises(owner.WeakPassword):
        owner.set_password(db, "short")
    assert owner.password_set(db) is False


def test_changing_the_password_needs_the_current_one_and_ends_every_session(db):
    owner.set_password(db, PASSWORD)
    session = owner.start_session(db)

    with pytest.raises(owner.WrongPassword):
        owner.set_password(db, "another long password", current="wrong password")
    assert owner.session_valid(db, session)

    owner.set_password(db, "another long password", current=PASSWORD)
    assert owner.verify(db, "another long password") and not owner.session_valid(db, session)


def test_removing_the_password_needs_the_current_one_and_ends_every_session(db):
    owner.set_password(db, PASSWORD)
    session = owner.start_session(db)

    with pytest.raises(owner.WrongPassword):
        owner.remove_password(db, "wrong password")
    owner.remove_password(db, PASSWORD)

    assert owner.password_set(db) is False and not owner.session_valid(db, session)


def test_a_session_ends_after_its_idle_time_its_lifetime_or_sign_out(db):
    now = [1000.0]
    clock = lambda: now[0]  # noqa: E731
    owner.set_password(db, PASSWORD)
    session = owner.start_session(db, clock)

    now[0] += owner.IDLE_SECONDS - 1
    assert owner.session_valid(db, session, clock)
    now[0] += owner.IDLE_SECONDS + 1
    assert not owner.session_valid(db, session, clock)

    other = owner.start_session(db, clock)
    for _ in range(int(owner.LIFETIME_SECONDS // owner.IDLE_SECONDS) + 1):
        now[0] += owner.IDLE_SECONDS - 60
        owner.session_valid(db, other, clock)
    assert not owner.session_valid(db, other, clock)

    third = owner.start_session(db, clock)
    owner.end_session(db, third)
    assert not owner.session_valid(db, third, clock)


def test_only_the_hash_of_a_session_id_is_stored(db):
    session = owner.start_session(db)

    stored = [row[0] for row in db.connection().execute("SELECT id_hash FROM owner_sessions")]
    assert stored and session not in stored


def test_failed_sign_ins_from_one_address_are_slowed_down(db):
    now = [5000.0]
    throttle = owner.SignInThrottle(db, clock=lambda: now[0])
    for _ in range(owner.FAILURE_LIMIT):
        wait, rows = throttle.reserve("10.0.0.9")
        assert wait == 0 and rows

    wait, rows = throttle.reserve("10.0.0.9")
    assert wait > 0 and rows == []
    assert throttle.reserve("10.0.0.10")[0] == 0

    now[0] += owner.WINDOW_SECONDS + 1
    assert throttle.reserve("10.0.0.9")[0] == 0


def test_a_successful_sign_in_releases_its_own_attempt(db):
    throttle = owner.SignInThrottle(db, clock=lambda: 5000.0)
    for _ in range(owner.FAILURE_LIMIT - 1):
        throttle.reserve("10.0.0.9")
    wait, rows = throttle.reserve("10.0.0.9")
    throttle.succeeded(rows)

    assert throttle.reserve("10.0.0.9")[0] == 0


def test_one_address_failing_does_not_block_another_or_the_owner_at_this_computer(db):
    throttle = owner.SignInThrottle(db, clock=lambda: 5000.0)
    for _ in range(owner.FAILURE_LIMIT + 1):
        throttle.reserve("172.17.0.1")

    assert throttle.reserve("172.17.0.1")[0] > 0
    assert throttle.reserve("203.0.113.7")[0] == 0
    assert throttle.reserve(None)[0] == 0


def test_the_global_limit_holds_every_address_but_not_the_owner_at_this_computer(db):
    throttle = owner.SignInThrottle(db, clock=lambda: 5000.0)
    for index in range(owner.GLOBAL_FAILURE_LIMIT):
        assert throttle.reserve(f"10.1.{index // 200}.{index % 200}")[0] == 0

    assert throttle.reserve("198.51.100.4")[0] > 0
    assert throttle.reserve(None)[0] == 0


def test_the_owner_at_this_computer_is_still_slowed_down_after_their_own_failures(db):
    throttle = owner.SignInThrottle(db, clock=lambda: 5000.0)
    for _ in range(owner.FAILURE_LIMIT):
        throttle.reserve(None)

    assert throttle.reserve(None)[0] > 0
    assert throttle.reserve("203.0.113.7")[0] == 0
