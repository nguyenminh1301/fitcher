"""Server-side sessions and the sign-in throttle over the app state."""

import hashlib

import pytest

from state_fixtures import new_state

from app.auth import accounts, sessions

HOUR = 3600.0
DAY = 24 * HOUR


class Clock:
    def __init__(self, now: float = 1_000_000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def db(tmp_path):
    return new_state(tmp_path)[0]


@pytest.fixture
def account(db):
    return accounts.create(db, "ana@example.com", "Ana", "correct horse", ["viewer", "admin"])


def test_a_new_session_resolves_to_its_account_principal(db, account):
    token = sessions.start(db, account.id)

    principal = sessions.principal_for(db, token)
    assert principal.user_id == account.id
    assert principal.display_name == "Ana"
    assert principal.roles == ("admin", "viewer")


def test_the_session_id_is_32_random_bytes_stored_only_as_a_hash(db, account):
    first, second = sessions.start(db, account.id), sessions.start(db, account.id)

    assert first != second
    assert len(first) >= 43
    stored = {row[0] for row in db.connection().execute("SELECT id_hash FROM sessions")}
    assert stored == {hashlib.sha256(token.encode()).hexdigest() for token in (first, second)}


@pytest.mark.parametrize("token", ["", "unknown", "x" * 43])
def test_an_unknown_session_resolves_to_nobody(db, token):
    assert sessions.principal_for(db, token) is None


def test_a_session_expires_after_12_hours_idle(db, account):
    clock = Clock()
    token = sessions.start(db, account.id, clock=clock)

    clock.now += 11 * HOUR
    assert sessions.principal_for(db, token, clock=clock) is not None
    clock.now += 11 * HOUR
    assert sessions.principal_for(db, token, clock=clock) is not None
    clock.now += 12 * HOUR + 1
    assert sessions.principal_for(db, token, clock=clock) is None
    assert db.connection().execute("SELECT count(*) FROM sessions").fetchone()[0] == 0


def test_a_session_expires_30_days_after_it_started_even_when_used(db, account):
    clock = Clock()
    token = sessions.start(db, account.id, clock=clock)

    for _ in range(59):
        clock.now += 12 * HOUR
        assert sessions.principal_for(db, token, clock=clock) is not None
    clock.now += 12 * HOUR + 1
    assert sessions.principal_for(db, token, clock=clock) is None


def test_ending_a_session_signs_it_out(db, account):
    token = sessions.start(db, account.id)

    sessions.end(db, token)

    assert sessions.principal_for(db, token) is None


def test_a_password_change_and_a_disable_end_every_session_of_the_account(db, account):
    other = accounts.create(db, "bob@example.com", "Bob", "correct horse", ["admin"])
    first, second = sessions.start(db, account.id), sessions.start(db, account.id)
    kept = sessions.start(db, other.id)

    accounts.set_password(db, account.id, "battery staple")
    assert sessions.principal_for(db, first) is None

    renewed = sessions.start(db, account.id)
    accounts.update(db, account.id, enabled=False)
    assert sessions.principal_for(db, second) is None
    assert sessions.principal_for(db, renewed) is None
    assert sessions.principal_for(db, kept) is not None


def test_a_role_change_reaches_the_next_request(db, account):
    token = sessions.start(db, account.id)

    accounts.update(db, account.id, roles=["admin", "pack_reviewer"])

    assert sessions.principal_for(db, token).roles == ("admin", "pack_reviewer")


def test_the_throttle_refuses_a_key_after_five_failures_in_fifteen_minutes(db):
    clock = Clock()
    throttle = sessions.SignInThrottle(db, clock=clock)
    keys = ["email:ana@example.com", "address:10.0.0.1"]

    for _ in range(5):
        assert throttle.retry_after(keys) == 0
        throttle.failed(keys)
    wait = throttle.retry_after(keys)
    assert 0 < wait <= 15 * 60

    clock.now += wait
    assert throttle.retry_after(keys) == 0


def test_an_address_gets_more_failures_than_one_email(db):
    throttle = sessions.SignInThrottle(db, clock=Clock())

    for index in range(19):
        throttle.failed([f"email:user{index}@example.com", "address:10.0.0.1"])

    assert throttle.retry_after(["email:new@example.com", "address:10.0.0.1"]) == 0
    throttle.failed(["address:10.0.0.1"])
    assert throttle.retry_after(["email:new@example.com", "address:10.0.0.1"]) > 0


def test_a_successful_sign_in_clears_the_email_failures(db):
    throttle = sessions.SignInThrottle(db, clock=Clock())
    for _ in range(4):
        throttle.failed(["email:ana@example.com"])

    throttle.succeeded("email:ana@example.com")
    throttle.failed(["email:ana@example.com"])

    assert throttle.retry_after(["email:ana@example.com"]) == 0
