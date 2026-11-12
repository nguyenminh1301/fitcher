"""Access token verification against a JWKS served by a local test key."""

from auth_fixtures import AUDIENCE, ISSUER, KEY, FakeJwks, SigningKey, claims, token, verifier
import jwt
import pytest

from app.auth.jwt import AuthError, AuthUnavailable, JwksCache


def test_a_valid_token_gives_its_user_and_roles():
    principal = verifier().verify(token())

    assert principal.user_id == "lab.viewer"
    assert principal.subject == "user-1"
    assert principal.display_name == "Lab Viewer"
    assert principal.roles == ("viewer", "default-roles-lab", "offline_access")


def test_a_token_without_a_username_is_identified_by_its_subject():
    principal = verifier().verify(token(preferred_username=None, name=None))

    assert principal.user_id == "user-1"
    assert principal.display_name == "user-1"


@pytest.mark.parametrize(("overrides", "reason"), [
    ({"exp": 1_000_000}, "expired"),
    ({"iss": "http://elsewhere.test/realms/lab"}, "issuer"),
    ({"aud": "another-client"}, "audience"),
    ({"exp": None}, "exp"),
    ({"sub": None}, "sub"),
])
def test_tokens_with_bad_claims_are_rejected(overrides, reason):
    with pytest.raises(AuthError, match=f"(?i){reason}"):
        verifier().verify(token(**overrides))


def test_an_audience_list_containing_the_api_is_accepted():
    assert verifier().verify(token(aud=["account", AUDIENCE])).user_id == "lab.viewer"


def test_a_token_signed_by_another_key_with_a_known_kid_is_rejected():
    forged = SigningKey(KEY.kid)

    with pytest.raises(AuthError, match="(?i)signature"):
        verifier().verify(token(forged))


def test_a_token_signed_with_a_shared_secret_is_rejected():
    hs256 = jwt.encode(claims(), "secret-secret-secret-secret-secret", algorithm="HS256", headers={"kid": KEY.kid})

    with pytest.raises(AuthError, match="algorithm"):
        verifier().verify(hs256)


@pytest.mark.parametrize("text", ["", "not-a-token", "a.b.c"])
def test_malformed_tokens_are_rejected(text):
    with pytest.raises(AuthError):
        verifier().verify(text)


def test_the_jwks_is_fetched_once_for_many_tokens():
    jwks = FakeJwks(KEY)
    check = verifier(jwks)

    for _ in range(3):
        check.verify(token())

    assert jwks.fetches == 1


def test_an_unknown_kid_refreshes_the_jwks_once():
    rotated = SigningKey("key-2")
    jwks = FakeJwks(KEY)
    check = verifier(jwks, min_refresh_seconds=0)
    check.verify(token())
    jwks.keys.append(rotated)

    assert check.verify(token(rotated)).user_id == "lab.viewer"
    assert jwks.fetches == 2


def test_a_kid_missing_after_the_refresh_is_rejected():
    jwks = FakeJwks(KEY)

    with pytest.raises(AuthError, match="key"):
        verifier(jwks, min_refresh_seconds=0).verify(token(SigningKey("unknown")))
    assert jwks.fetches == 1


def test_unknown_kids_do_not_refresh_more_often_than_the_minimum_interval():
    now = [100.0]
    jwks = FakeJwks(KEY)
    check = verifier(jwks, min_refresh_seconds=30, clock=lambda: now[0])
    check.verify(token())

    for _ in range(3):
        with pytest.raises(AuthError):
            check.verify(token(SigningKey("unknown")))
    assert jwks.fetches == 1
    now[0] += 31
    with pytest.raises(AuthError):
        check.verify(token(SigningKey("unknown")))
    assert jwks.fetches == 2


def test_an_unreachable_jwks_is_unavailable_not_unauthorized():
    def down(url: str) -> dict:
        raise OSError("connection refused")

    cache = JwksCache("http://keycloak.test/certs", fetch=down)

    with pytest.raises(AuthUnavailable):
        cache.key("key-1")


def test_the_issuer_must_match_exactly():
    with pytest.raises(AuthError, match="(?i)issuer"):
        verifier().verify(token(iss=ISSUER + "/"))
