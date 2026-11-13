"""Local accounts in the app state: unique e-mail, Argon2id hashes, roles and the last-admin rule."""

import pytest

from state_fixtures import new_state

from app.auth import accounts


@pytest.fixture
def db(tmp_path):
    return new_state(tmp_path)[0]


def test_an_account_is_stored_with_a_lower_cased_email_and_its_roles(db):
    created = accounts.create(db, " Ana@Example.COM ", "Ana", "correct horse", ["viewer", "admin"])

    found = accounts.get(db, created.id)
    assert found == created
    assert found.email == "ana@example.com"
    assert found.display_name == "Ana"
    assert found.roles == ("admin", "viewer")
    assert found.enabled


def test_the_password_is_stored_as_an_argon2id_hash(db):
    created = accounts.create(db, "ana@example.com", "Ana", "correct horse", [])

    stored = db.connection().execute("SELECT password_hash FROM accounts WHERE id = ?", (created.id,)).fetchone()[0]
    assert stored.startswith("$argon2id$")
    assert "correct horse" not in stored


def test_an_email_can_belong_to_one_account_only(db):
    accounts.create(db, "ana@example.com", "Ana", "correct horse", [])

    with pytest.raises(accounts.DuplicateEmail):
        accounts.create(db, "ANA@example.com", "Other", "correct horse", [])


@pytest.mark.parametrize("email", ["", "no-at-sign", "@example.com", "ana@"])
def test_an_email_without_a_local_part_and_a_domain_is_refused(db, email):
    with pytest.raises(accounts.AccountError):
        accounts.create(db, email, "Ana", "correct horse", [])


def test_a_short_password_is_refused(db):
    with pytest.raises(accounts.WeakPassword):
        accounts.create(db, "ana@example.com", "Ana", "short", [])


def test_a_given_id_is_kept(db):
    created = accounts.create(db, "viewer@example.com", "Viewer", "correct horse", ["viewer"], account_id="lab.viewer")

    assert created.id == "lab.viewer"


def test_authenticate_returns_the_account_for_the_right_password_only(db):
    created = accounts.create(db, "ana@example.com", "Ana", "correct horse", [])

    assert accounts.authenticate(db, "ANA@example.com", "correct horse") == created
    assert accounts.authenticate(db, "ana@example.com", "wrong horse") is None
    assert accounts.authenticate(db, "nobody@example.com", "correct horse") is None


def test_a_disabled_account_cannot_authenticate(db):
    created = accounts.create(db, "ana@example.com", "Ana", "correct horse", [])
    accounts.update(db, created.id, enabled=False)

    assert accounts.authenticate(db, "ana@example.com", "correct horse") is None


def test_set_password_replaces_the_hash(db):
    created = accounts.create(db, "ana@example.com", "Ana", "correct horse", [])

    accounts.set_password(db, created.id, "battery staple")

    assert accounts.authenticate(db, "ana@example.com", "correct horse") is None
    assert accounts.authenticate(db, "ana@example.com", "battery staple") == accounts.get(db, created.id)


def test_update_changes_the_name_roles_and_status(db):
    created = accounts.create(db, "ana@example.com", "Ana", "correct horse", ["viewer"])

    updated = accounts.update(db, created.id, display_name="Ana B", roles=["pack_reviewer"], enabled=False)

    assert (updated.display_name, updated.roles, updated.enabled) == ("Ana B", ("pack_reviewer",), False)
    assert accounts.get(db, created.id) == updated


def test_an_unknown_account_cannot_be_changed(db):
    with pytest.raises(accounts.UnknownAccount):
        accounts.update(db, "missing", enabled=False)
    with pytest.raises(accounts.UnknownAccount):
        accounts.set_password(db, "missing", "correct horse")


def test_the_last_enabled_admin_cannot_be_disabled_or_demoted(db):
    admin = accounts.create(db, "admin@example.com", "Admin", "correct horse", ["admin"])

    with pytest.raises(accounts.LastAdmin):
        accounts.update(db, admin.id, enabled=False)
    with pytest.raises(accounts.LastAdmin):
        accounts.update(db, admin.id, roles=["viewer"])
    assert accounts.get(db, admin.id) == admin


def test_an_admin_can_be_disabled_while_another_enabled_admin_remains(db):
    first = accounts.create(db, "first@example.com", "First", "correct horse", ["admin"])
    second = accounts.create(db, "second@example.com", "Second", "correct horse", ["admin"])

    accounts.update(db, first.id, enabled=False)

    with pytest.raises(accounts.LastAdmin):
        accounts.update(db, second.id, roles=[])


def test_accounts_are_listed_by_email(db):
    accounts.create(db, "zed@example.com", "Zed", "correct horse", [])
    accounts.create(db, "ana@example.com", "Ana", "correct horse", [])

    assert [account.email for account in accounts.list_all(db)] == ["ana@example.com", "zed@example.com"]
