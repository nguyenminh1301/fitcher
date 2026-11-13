import pytest

from app.state import migrate, setup
from app.state.db import StateDb
from app.state.settings import SettingError, SettingSpec, Settings


@pytest.fixture
def db(tmp_path):
    db = StateDb(tmp_path / "app.db")
    migrate.apply_pending(db)
    return db


def test_settings_return_the_default_until_set(db):
    settings = Settings(db)
    assert settings.get("instance", "mode") is None
    settings.set("instance", "mode", "team")
    assert settings.get("instance", "mode") == "team"
    assert Settings(db).get("instance", "mode") == "team"


def test_settings_validate_type_and_choices(db):
    settings = Settings(db)
    with pytest.raises(SettingError):
        settings.set("instance", "mode", "everyone")
    with pytest.raises(SettingError):
        settings.set("setup", "complete", "yes")
    with pytest.raises(SettingError, match="unknown"):
        settings.set("nope", "x", 1)


def test_settings_can_register_a_typed_setting(db):
    spec = SettingSpec(type=int, default=3)
    settings = Settings(db, extra={("demo", "count"): spec})
    assert settings.get("demo", "count") == 3
    settings.set("demo", "count", 5)
    assert settings.get("demo", "count") == 5


def test_a_new_instance_has_every_step_pending_and_is_incomplete(db):
    status = setup.status(db)
    assert status.mode is None and not status.complete
    assert status.steps and all(step.state == "pending" for step in status.steps)


def test_choosing_a_mode_marks_its_step_done_and_is_kept(db):
    setup.set_mode(db, "team", setup.FirstAdmin("ana@example.com", "Ana", "correct horse"), ["viewer"])
    status = setup.status(db)
    assert status.mode == "team"
    assert {s.id: s.state for s in status.steps}["mode"] == "done"


def test_team_mode_without_an_admin_needs_the_first_admin(db):
    with pytest.raises(setup.FirstAdminNeeded):
        setup.set_mode(db, "team")
    assert setup.status(db).mode is None


def test_the_first_admin_takes_the_owner_id_and_the_owner_roles(db):
    created = setup.set_mode(db, "team", setup.FirstAdmin("ana@example.com", "Ana", "correct horse"), ["viewer"])

    assert (created.id, created.roles) == ("owner", ("admin", "viewer"))
    assert setup.set_mode(db, "team") is None


def test_unknown_mode_and_step_are_rejected(db):
    with pytest.raises(setup.SetupError):
        setup.set_mode(db, "everyone")
    with pytest.raises(setup.UnknownStep):
        setup.skip(db, "nope")


def test_skip_marks_a_step_skipped(db):
    setup.skip(db, "mode")
    assert {s.id: s.state for s in setup.status(db).steps}["mode"] == "skipped"


def test_complete_needs_every_step_decided(db):
    with pytest.raises(setup.SetupError, match="mode"):
        setup.complete(db)
    setup.set_mode(db, "individual")
    with pytest.raises(setup.SetupError, match="models"):
        setup.complete(db)
    setup.mark_done(db, "models")
    setup.complete(db)
    assert setup.status(db).complete
