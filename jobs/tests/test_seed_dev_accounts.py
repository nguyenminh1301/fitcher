"""``jobs/seed_dev_accounts.py`` over a temporary app state."""

import pytest

from jobs import seed_dev_accounts as job

from app.auth import accounts
from app.state.db import StateDb
from app.state.migrate import apply_pending
from app.state.settings import Settings

PASSWORD = "dev-password-1"


@pytest.fixture
def db(tmp_path):
    state = StateDb(tmp_path / "app.db")
    apply_pending(state)
    return state


def test_the_six_development_users_can_sign_in_with_their_roles(db, capsys):
    assert job.seed(db, job.read_accounts(), PASSWORD) == 6

    admin = accounts.authenticate(db, "lab.admin@fitcher.test", PASSWORD)
    assert (admin.id, admin.roles) == ("lab.admin", ("admin", "analyst"))
    assert [account.id for account in accounts.list_all(db)] == [
        "lab.admin", "lab.analyst", "lab.marketing", "lab.northwest", "lab.partner", "lab.reviewer",
    ]
    assert PASSWORD not in capsys.readouterr().out


def test_the_instance_is_put_in_team_mode(db):
    job.seed(db, job.read_accounts(), PASSWORD)

    assert Settings(db).get("instance", "mode") == "team"


def test_a_second_run_resets_passwords_roles_and_status(db):
    job.seed(db, job.read_accounts(), PASSWORD)
    accounts.update(db, "lab.analyst", roles=["marketing"], enabled=False)

    job.seed(db, job.read_accounts(), "another-password")

    analyst = accounts.authenticate(db, "lab.analyst@fitcher.test", "another-password")
    assert analyst is not None and analyst.roles == ("analyst",)
    assert len(accounts.list_all(db)) == 6


def test_the_password_comes_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("FITCHER_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("DEV_ACCOUNT_PASSWORD", raising=False)

    assert job.main() == 1

    monkeypatch.setenv("DEV_ACCOUNT_PASSWORD", "short")
    assert job.main() == 1

    monkeypatch.setenv("DEV_ACCOUNT_PASSWORD", PASSWORD)
    assert job.main() == 0


def test_a_reseed_restores_the_admin_when_another_account_holds_the_only_admin_role(db):
    job.seed(db, job.read_accounts(), PASSWORD)
    accounts.update(db, "lab.analyst", roles=["analyst", "admin"])
    accounts.update(db, "lab.admin", enabled=False)

    job.seed(db, job.read_accounts(), PASSWORD)

    assert accounts.get(db, "lab.admin").enabled
    assert accounts.get(db, "lab.analyst").roles == ("analyst",)
