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
    assert settings.get("limits", "concurrent_questions") == 4
    settings.set("limits", "concurrent_questions", 2)
    assert Settings(db).get("limits", "concurrent_questions") == 2


def test_settings_validate_type_and_choices(db):
    settings = Settings(db)
    with pytest.raises(SettingError):
        settings.set("llm.embedding", "backend", "everywhere")
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
    assert not status.complete
    assert [step.id for step in status.steps] == ["models", "data"]
    assert status.steps and all(step.state == "pending" for step in status.steps)


def test_an_unknown_step_is_rejected(db):
    with pytest.raises(setup.UnknownStep):
        setup.skip(db, "nope")
    with pytest.raises(setup.UnknownStep):
        setup.skip(db, "mode")
    # Company documents are turned on or off on the Documents page, not in the setup.
    with pytest.raises(setup.UnknownStep):
        setup.skip(db, "documents")


def test_skip_marks_a_step_skipped(db):
    setup.skip(db, "data")
    assert {s.id: s.state for s in setup.status(db).steps}["data"] == "skipped"


def test_complete_needs_every_step_decided(db):
    with pytest.raises(setup.SetupError, match="models"):
        setup.complete(db)
    setup.mark_done(db, "models")
    with pytest.raises(setup.SetupError, match="data"):
        setup.complete(db)
    setup.skip(db, "data")
    setup.complete(db)
    assert setup.status(db).complete


def test_company_documents_are_off_on_a_new_instance(db):
    assert Settings(db).get("documents", "enabled") is False
