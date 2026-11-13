"""The JWKS cache that OIDC sign-in checks ID tokens with."""

import pytest

from auth_fixtures import KEY, FakeJwks, JWKS_URL, SigningKey

from app.auth.jwt import AuthError, AuthUnavailable, JwksCache


def cache(jwks: FakeJwks, **options) -> JwksCache:
    return JwksCache(JWKS_URL, fetch=jwks, **options)


def test_the_jwks_is_fetched_once_for_many_lookups():
    jwks = FakeJwks(KEY)
    keys = cache(jwks)

    for _ in range(3):
        keys.key(KEY.kid)

    assert jwks.fetches == 1


def test_an_unknown_kid_refreshes_the_jwks_once():
    rotated = SigningKey("key-2")
    jwks = FakeJwks(KEY)
    keys = cache(jwks, min_refresh_seconds=0)
    keys.key(KEY.kid)
    jwks.keys.append(rotated)

    assert keys.key(rotated.kid) is not None
    assert jwks.fetches == 2


def test_a_kid_missing_after_the_refresh_is_rejected():
    jwks = FakeJwks(KEY)

    with pytest.raises(AuthError, match="key"):
        cache(jwks, min_refresh_seconds=0).key("unknown")
    assert jwks.fetches == 1


def test_unknown_kids_do_not_refresh_more_often_than_the_minimum_interval():
    now = [100.0]
    jwks = FakeJwks(KEY)
    keys = cache(jwks, min_refresh_seconds=30, clock=lambda: now[0])
    keys.key(KEY.kid)

    for _ in range(3):
        with pytest.raises(AuthError):
            keys.key("unknown")
    assert jwks.fetches == 1
    now[0] += 31
    with pytest.raises(AuthError):
        keys.key("unknown")
    assert jwks.fetches == 2


def test_an_unreachable_jwks_is_unavailable_not_unauthorized():
    def down(url: str) -> dict:
        raise OSError("connection refused")

    with pytest.raises(AuthUnavailable):
        JwksCache(JWKS_URL, fetch=down).key("key-1")
