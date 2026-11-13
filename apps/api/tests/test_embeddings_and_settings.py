"""Engine settings read from the environment."""

import pytest

from app.config import SettingsError, load_settings


def test_settings_defaults():
    settings = load_settings({})

    assert settings.qdrant_url == "http://qdrant:6333"
    assert settings.column_values_top_k == 10_000
    assert settings.compiled_pack_dir == "build/packs"
    assert settings.documents_dir == "build/documents"
    assert settings.document_max_bytes == 20 * 1024 * 1024
    assert settings.packs_dir == "packs"


@pytest.mark.parametrize("value", ["abc", "0"])
def test_invalid_document_size_cap_is_rejected(value):
    with pytest.raises(SettingsError, match="DOCUMENT_MAX_BYTES"):
        load_settings({"DOCUMENT_MAX_BYTES": value})


@pytest.mark.parametrize("value", ["abc", "0", "-5"])
def test_invalid_numeric_setting_is_rejected(value):
    with pytest.raises(SettingsError, match="COLUMN_VALUES_TOP_K"):
        load_settings({"COLUMN_VALUES_TOP_K": value})


def test_screening_settings_default_to_log_mode_and_the_plan_thresholds():
    settings = load_settings({})
    assert (settings.screen_mode, settings.screen_flag_at, settings.screen_block_at, settings.guard_model_dir) == (
        "log", 0.5, 0.9, "build/guard_model",
    )


@pytest.mark.parametrize(("env", "message"), [
    ({"SCREEN_MODE": "strict"}, "SCREEN_MODE must be one of log, enforce"),
    ({"SCREEN_FLAG_AT": "high"}, "SCREEN_FLAG_AT must be a number"),
    ({"SCREEN_BLOCK_AT": "1.5"}, "SCREEN_BLOCK_AT must be above 0 and at most 1"),
    ({"SCREEN_FLAG_AT": "0.95", "SCREEN_BLOCK_AT": "0.9"}, "must not be above SCREEN_BLOCK_AT"),
])
def test_invalid_screening_settings_are_rejected(env, message):
    with pytest.raises(SettingsError, match=message):
        load_settings(env)

