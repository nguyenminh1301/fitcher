"""The pack the instance answers from (DECISIONS §16: one active pack per instance).

``ACTIVE_PACK`` wins when it is set, so a development or scripted setup keeps naming its pack; otherwise the app
state records the pack an instant pack made active.
"""

from collections.abc import Mapping
import os

from app.state.db import StateDb
from app.state.settings import Settings

GROUP, KEY = "pack", "active"


def active_pack(db: StateDb, env: Mapping[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    return env.get("ACTIVE_PACK") or Settings(db).get(GROUP, KEY) or ""


def set_active_pack(db: StateDb, name: str) -> None:
    Settings(db).set(GROUP, KEY, name)
