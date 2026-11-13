"""OpenID Connect sign-in against a fake provider: PKCE, state, nonce, ID-token checks and the first-sign-in account."""

import base64
from urllib.parse import parse_qs, urlsplit

import pytest

from auth_fixtures import SigningKey
from oidc_fixtures import CLIENT_ID, CLIENT_SECRET, ISSUER, FakeProvider
from state_fixtures import new_state

from app.auth import accounts, oidc

REDIRECT = "http://localhost:3000/auth/oidc/callback"
INSTANCE_ROLES = ["viewer", "pack_reviewer", "admin"]


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


@pytest.fixture
def db(tmp_path):
    return new_state(tmp_path)[0]


@pytest.fixture
def idp():
    return FakeProvider()


@pytest.fixture
def provider(idp):
    return oidc.Provider(oidc.OidcConfig(ISSUER, CLIENT_ID, CLIENT_SECRET, "groups"), idp.client())


def authorize(db, idp, provider, clock=None):
    """Start a sign-in and play the provider's part; returns the callback's state and code."""
    url = oidc.start(db, provider, REDIRECT, **({"clock": clock} if clock else {}))
    query = {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}
    return query["state"], idp.issue_code(query["nonce"], query["code_challenge"], query["redirect_uri"])


def test_start_sends_the_browser_to_the_provider_with_pkce_state_and_nonce(db, provider):
    url = oidc.start(db, provider, REDIRECT)

    parts = urlsplit(url)
    query = {key: values[0] for key, values in parse_qs(parts.query).items()}
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == f"{ISSUER}/protocol/openid-connect/auth"
    assert query["response_type"] == "code"
    assert query["client_id"] == CLIENT_ID
    assert query["redirect_uri"] == REDIRECT
    assert set(query["scope"].split()) == {"openid", "email", "profile"}
    assert query["code_challenge_method"] == "S256"
    assert len(query["state"]) >= 43 and len(query["nonce"]) >= 43
    assert len(base64.urlsafe_b64decode(query["code_challenge"] + "=")) == 32


def test_the_first_sign_in_creates_an_account_with_the_claim_roles_the_instance_has(db, idp, provider):
    state, code = authorize(db, idp, provider)

    account = oidc.finish(db, provider, state, code, INSTANCE_ROLES)

    assert (account.email, account.display_name, account.roles) == ("carol@example.com", "Carol", ("viewer",))
    assert accounts.authenticate(db, "carol@example.com", "") is None


def test_a_later_sign_in_finds_the_same_account_and_keeps_its_roles(db, idp, provider):
    first = oidc.finish(db, provider, *authorize(db, idp, provider), INSTANCE_ROLES)
    accounts.update(db, first.id, roles=["pack_reviewer"])
    idp.claims["groups"] = ["admin"]

    again = oidc.finish(db, provider, *authorize(db, idp, provider), INSTANCE_ROLES)

    assert again.id == first.id
    assert again.roles == ("pack_reviewer",)


@pytest.mark.parametrize(("claim", "roles"), [(None, ()), ("viewer", ("viewer",)), (["admin", 7], ("admin",))])
def test_the_roles_claim_may_be_absent_a_string_or_a_list(db, idp, provider, claim, roles):
    idp.claims["groups"] = claim

    account = oidc.finish(db, provider, *authorize(db, idp, provider), INSTANCE_ROLES)

    assert account.roles == roles


def test_the_client_authenticates_to_the_token_endpoint_with_its_secret(db, idp, provider):
    oidc.finish(db, provider, *authorize(db, idp, provider), INSTANCE_ROLES)

    expected = "Basic " + base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    assert idp.token_requests[0]["authorization"] == expected


def test_a_state_works_once(db, idp, provider):
    state, code = authorize(db, idp, provider)
    oidc.finish(db, provider, state, code, INSTANCE_ROLES)

    with pytest.raises(oidc.OidcError):
        oidc.finish(db, provider, state, code, INSTANCE_ROLES)


def test_an_unknown_or_expired_state_is_refused(db, idp, provider):
    with pytest.raises(oidc.OidcError):
        oidc.finish(db, provider, "unknown", "code", INSTANCE_ROLES)

    clock = Clock()
    state, code = authorize(db, idp, provider, clock)
    clock.now += 10 * 60 + 1
    with pytest.raises(oidc.OidcError):
        oidc.finish(db, provider, state, code, INSTANCE_ROLES, clock=clock)


@pytest.mark.parametrize("overrides", [
    {"nonce": "other"},
    {"aud": "another-client"},
    {"iss": "https://evil.example.com"},
    {"exp": 1_000_000},
    {"sub": None},
])
def test_an_id_token_that_fails_a_check_is_refused(db, idp, provider, overrides, monkeypatch):
    original = idp.id_token
    monkeypatch.setattr(idp, "id_token", lambda nonce: original(nonce, **overrides))

    with pytest.raises(oidc.OidcError):
        oidc.finish(db, provider, *authorize(db, idp, provider), INSTANCE_ROLES)
    assert accounts.list_all(db) == []


def test_an_id_token_signed_by_another_key_is_refused(db, idp, provider):
    idp.key = SigningKey(idp.published.kid)

    with pytest.raises(oidc.OidcError):
        oidc.finish(db, provider, *authorize(db, idp, provider), INSTANCE_ROLES)


def test_an_email_that_a_local_account_already_uses_is_not_taken_over(db, idp, provider):
    accounts.create(db, "carol@example.com", "Carol", "correct horse", ["admin"])

    with pytest.raises(oidc.OidcError, match="already"):
        oidc.finish(db, provider, *authorize(db, idp, provider), INSTANCE_ROLES)


def test_a_disabled_account_cannot_sign_in_through_the_provider(db, idp, provider):
    accounts.create(db, "admin@example.com", "Admin", "correct horse", ["admin"])
    account = oidc.finish(db, provider, *authorize(db, idp, provider), INSTANCE_ROLES)
    accounts.update(db, account.id, enabled=False)

    with pytest.raises(oidc.OidcError):
        oidc.finish(db, provider, *authorize(db, idp, provider), INSTANCE_ROLES)


def test_discovery_must_name_the_configured_issuer(idp):
    provider = oidc.Provider(oidc.OidcConfig("https://idp.example.com/realms/other", CLIENT_ID, CLIENT_SECRET, "groups"),
                             idp.client())

    with pytest.raises(oidc.OidcError):
        provider.discovery()


def test_discovery_is_read_once(db, idp, provider):
    oidc.start(db, provider, REDIRECT)
    oidc.start(db, provider, REDIRECT)

    assert idp.discovery_fetches == 1
