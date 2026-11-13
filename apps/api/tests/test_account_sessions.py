"""Server-side session of each signed-in account, and the sign-in throttle, over the app state."""

import hashlib

import pytest

from state_fixtures import new_state

from app.auth import accounts, account_sessions

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
    token = account_sessions.start(db, account.id)

    principal = account_sessions.principal_for(db, token)
    assert principal.user_id == account.id
    assert principal.display_name == "Ana"
    assert principal.roles == ("admin", "viewer")


def test_the_session_id_is_32_random_bytes_stored_only_as_a_hash(db, account):
    first, second = account_sessions.start(db, account.id), account_sessions.start(db, account.id)

    assert first != second
    assert len(first) >= 43
    stored = {row[0] for row in db.connection().execute("SELECT id_hash FROM account_sessions")}
    assert stored == {hashlib.sha256(token.encode()).hexdigest() for token in (first, second)}


@pytest.mark.parametrize("token", ["", "unknown", "x" * 43])
def test_an_unknown_session_resolves_to_nobody(db, token):
    assert account_sessions.principal_for(db, token) is None


def test_a_session_expires_after_12_hours_idle(db, account):
    clock = Clock()
    token = account_sessions.start(db, account.id, clock=clock)

    clock.now += 11 * HOUR
    assert account_sessions.principal_for(db, token, clock=clock) is not None
    clock.now += 11 * HOUR
    assert account_sessions.principal_for(db, token, clock=clock) is not None
    clock.now += 12 * HOUR + 1
    assert account_sessions.principal_for(db, token, clock=clock) is None
    assert db.connection().execute("SELECT count(*) FROM account_sessions").fetchone()[0] == 0


def test_a_session_expires_30_days_after_it_started_even_when_used(db, account):
    clock = Clock()
    token = account_sessions.start(db, account.id, clock=clock)

    for _ in range(59):
        clock.now += 12 * HOUR
        assert account_sessions.principal_for(db, token, clock=clock) is not None
    clock.now += 12 * HOUR + 1
    assert account_sessions.principal_for(db, token, clock=clock) is None


def test_ending_a_session_signs_it_out(db, account):
    token = account_sessions.start(db, account.id)

    account_sessions.end(db, token)

    assert account_sessions.principal_for(db, token) is None


def test_a_password_change_and_a_disable_end_every_session_of_the_account(db, account):
    other = accounts.create(db, "bob@example.com", "Bob", "correct horse", ["admin"])
    first, second = account_sessions.start(db, account.id), account_sessions.start(db, account.id)
    kept = account_sessions.start(db, other.id)

    accounts.set_password(db, account.id, "battery staple")
    assert account_sessions.principal_for(db, first) is None

    renewed = account_sessions.start(db, account.id)
    accounts.update(db, account.id, enabled=False)
    assert account_sessions.principal_for(db, second) is None
    assert account_sessions.principal_for(db, renewed) is None
    assert account_sessions.principal_for(db, kept) is not None


def test_a_role_change_reaches_the_next_request(db, account):
    token = account_sessions.start(db, account.id)

    accounts.update(db, account.id, roles=["admin", "pack_reviewer"])

    assert account_sessions.principal_for(db, token).roles == ("admin", "pack_reviewer")


def test_each_attempt_is_counted_before_the_password_is_checked(db):
    clock = Clock()
    throttle = account_sessions.SignInThrottle(db, clock=clock)
    keys = ["email:ana@example.com", "address:10.0.0.1"]

    # Five attempts still being checked hold the five places, so a sixth parallel one is refused.
    for _ in range(5):
        wait, _ = throttle.reserve(keys)
        assert wait == 0
    wait, reservation = throttle.reserve(keys)
    assert 0 < wait <= 15 * 60
    assert reservation == []

    clock.now += wait
    assert throttle.reserve(keys)[0] == 0


def test_an_address_gets_more_failures_than_one_email(db):
    throttle = account_sessions.SignInThrottle(db, clock=Clock())

    for index in range(19):
        throttle.reserve([f"email:user{index}@example.com", "address:10.0.0.1"])

    assert throttle.reserve(["email:new@example.com", "address:10.0.0.1"])[0] == 0
    assert throttle.reserve(["email:new2@example.com", "address:10.0.0.1"])[0] > 0


def test_a_successful_sign_in_releases_only_its_own_places(db):
    throttle = account_sessions.SignInThrottle(db, clock=Clock())
    keys = ["email:ana@example.com", "address:10.0.0.1"]
    for _ in range(4):
        throttle.reserve(keys)

    _, reservation = throttle.reserve(keys)
    throttle.succeeded(reservation)

    assert throttle.reserve(keys)[0] == 0
    assert throttle.reserve(keys)[0] > 0


def test_a_success_does_not_free_the_places_of_attempts_still_being_checked(db):
    throttle = account_sessions.SignInThrottle(db, clock=Clock())
    keys = ["email:ana@example.com", "address:10.0.0.1"]
    in_progress = [throttle.reserve(keys) for _ in range(4)]
    assert all(wait == 0 for wait, _ in in_progress)

    _, reservation = throttle.reserve(keys)
    throttle.succeeded(reservation)

    # The four attempts still being checked keep their places; one more fits, then the limit holds.
    assert throttle.reserve(keys)[0] == 0
    assert throttle.reserve(keys)[0] > 0
