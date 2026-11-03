"""The per-user token bucket of /ask."""

import pytest

from app.api.rate_limit import RateLimiter


def limiter(per_minute: int):
    now = [0.0]
    return RateLimiter(per_minute, clock=lambda: now[0]), now


def test_a_user_may_ask_a_burst_of_the_per_minute_limit():
    limit, _ = limiter(3)

    assert [limit.acquire("u1") for _ in range(3)] == [0.0, 0.0, 0.0]
    assert limit.acquire("u1") == pytest.approx(20.0)


def test_tokens_refill_evenly_over_a_minute():
    limit, now = limiter(6)
    for _ in range(6):
        limit.acquire("u1")

    now[0] = 5.0
    assert limit.acquire("u1") == pytest.approx(5.0)
    now[0] = 10.0
    assert limit.acquire("u1") == 0.0
    assert limit.acquire("u1") > 0


def test_a_bucket_never_holds_more_than_the_limit():
    limit, now = limiter(2)
    now[0] = 3600.0

    assert [limit.acquire("u1") == 0 for _ in range(3)] == [True, True, False]


def test_users_have_their_own_buckets():
    limit, _ = limiter(1)

    assert limit.acquire("u1") == 0.0
    assert limit.acquire("u2") == 0.0
    assert limit.acquire("u1") > 0


def test_the_limit_must_be_positive():
    with pytest.raises(ValueError):
        RateLimiter(0)
