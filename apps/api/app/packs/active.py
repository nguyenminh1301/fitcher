"""The pack used last (DECISIONS §1, §15): where a new chat and the console start.

Each data source has its own pack and each conversation keeps its pack, so this is a default, not the only pack
the instance serves. ``ACTIVE_PACK`` wins when it is set, so a development or scripted setup keeps naming its
pack; otherwise the app state records the pack last built or asked.
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
