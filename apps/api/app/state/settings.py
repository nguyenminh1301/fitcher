"""Typed settings by group and key, stored as JSON in the app state.

Every setting has a spec (type, default and optional choices); reading an
unset setting returns its default and writing a value of the wrong type or
outside its choices is refused. Each later phase adds the specs of its own
settings to ``SPECS``.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from typing import Any

from app.llm.tiers import CHAT_TIERS
from app.state.db import StateDb


class SettingError(ValueError):
    """The setting is unknown or the value does not fit its spec."""


@dataclass(frozen=True)
class SettingSpec:
    type: type
    default: Any = None
    choices: tuple[Any, ...] | None = None


INSTANCE_MODES = ("individual", "team")

SPECS: dict[tuple[str, str], SettingSpec] = {
    ("instance", "mode"): SettingSpec(str, None, INSTANCE_MODES),
    ("setup", "complete"): SettingSpec(bool, False),
    # Each chat tier's model: {"provider_id": ..., "model": ...} (app/llm/routes.py).
    **{("llm.tiers", tier): SettingSpec(dict) for tier in CHAT_TIERS},
    # The embed tier's model and vector size; changing them needs a full reindex (DECISIONS §14).
    # The optional prompt-injection classifier (DECISIONS §9); the EN/VI rules always run.
    ("screening", "classifier_enabled"): SettingSpec(bool, False),
    # Unset until a provider proposes its embedding model or an admin chooses one.
    ("llm.embedding", "backend"): SettingSpec(str, None, ("local", "provider")),
    ("llm.embedding", "provider_id"): SettingSpec(str),
    ("llm.embedding", "model"): SettingSpec(str),
    ("llm.embedding", "dimensions"): SettingSpec(int),
}


class Settings:
    def __init__(self, db: StateDb, extra: dict[tuple[str, str], SettingSpec] | None = None):
        self._db = db
        self._specs = {**SPECS, **(extra or {})}

    def _spec(self, group: str, key: str) -> SettingSpec:
        try:
            return self._specs[(group, key)]
        except KeyError:
            raise SettingError(f"unknown setting {group}.{key}") from None

    def get(self, group: str, key: str) -> Any:
        spec = self._spec(group, key)
        row = self._db.connection().execute(
            "SELECT value FROM settings WHERE group_name = ? AND key = ?", (group, key)
        ).fetchone()
        return spec.default if row is None else json.loads(row[0])

    def set(self, group: str, key: str, value: Any) -> None:
        spec = self._spec(group, key)
        if type(value) is not spec.type:
            raise SettingError(f"{group}.{key} must be {spec.type.__name__}")
        if spec.choices is not None and value not in spec.choices:
            raise SettingError(f"{group}.{key} must be one of {', '.join(map(str, spec.choices))}")
        with self._db.write() as conn:
            conn.execute(
                "INSERT INTO settings (group_name, key, value, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(group_name, key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                (group, key, json.dumps(value), datetime.now(UTC).isoformat()),
            )
