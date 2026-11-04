"""Model tiers and the tier-to-alias mapping (DECISIONS §2 Model tiers).

Engine code calls a tier; ``TierMap`` turns it into an alias of the LiteLLM
catalog (``infra/litellm/catalog/``). The defaults come from
``MODEL_TIER_<TIER>`` settings. An ``admin`` maps a chat tier to another
eligible alias on the console's Models page; the change is a row in
``data_meta.model_tiers``, which ``TierMap`` reads again after at most
``CACHE_SECONDS``, so it needs no LiteLLM restart. ``embed`` always keeps its
default, because a new embedding model needs a full reindex. When the store
cannot be read, the last mapping read (or the defaults) stays in use.
"""

from collections.abc import Callable, Mapping
from datetime import datetime
import logging
import threading
import time
from typing import Protocol

CHAT_TIERS = ("fast", "sql-small", "sql-gen", "sql-gen-hard")
EMBED_TIER = "embed"
TIERS = (*CHAT_TIERS, EMBED_TIER)
CACHE_SECONDS = 30.0
# Aliases of the OpenAI catalog block, used when a MODEL_TIER_<TIER> setting is empty.
BUILT_IN_DEFAULTS = {
    "fast": "openai-small",
    "sql-small": "openai-small",
    "sql-gen": "openai-medium",
    "sql-gen-hard": "openai-large",
    "embed": "openai-embed",
}

_log = logging.getLogger(__name__)


class TierStoreError(RuntimeError):
    """The mapping store could not be read or written."""


def setting_name(tier: str) -> str:
    return "MODEL_TIER_" + tier.upper().replace("-", "_")


def tier_defaults(env: Mapping[str, str]) -> dict[str, str]:
    """The default alias of every tier from ``MODEL_TIER_<TIER>``, else the built-in default."""
    return {tier: env.get(setting_name(tier)) or BUILT_IN_DEFAULTS[tier] for tier in TIERS}


def provider_of(alias: str) -> str:
    """The provider an alias belongs to: catalog aliases are named ``<provider>-<size>``."""
    return alias.split("-", 1)[0]


def check_chat_tier(tier: str) -> None:
    if tier not in CHAT_TIERS:
        raise ValueError(f"unknown chat tier {tier!r}; use one of {list(CHAT_TIERS)}")


class TierStore(Protocol):
    def read(self) -> dict[str, str]:
        """The latest alias written for each tier that has a row."""

    def write(self, tier: str, alias: str, changed_by: str, changed_at: datetime) -> None:
        """Record ``alias`` as the tier's mapping."""


class TierMap:
    """Resolves a tier to its alias: the stored mapping when present, otherwise the default."""

    def __init__(
        self,
        defaults: Mapping[str, str],
        store: TierStore | None = None,
        ttl: float = CACHE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ):
        missing = [tier for tier in TIERS if not defaults.get(tier)]
        if missing:
            raise ValueError(f"no default alias for the tiers {missing}")
        self.defaults = dict(defaults)
        self._store = store
        self._ttl = ttl
        self._clock = clock
        self._stored: dict[str, str] = {}
        self._read_at: float | None = None
        self._lock = threading.Lock()

    def _refresh(self) -> None:
        if self._store is None:
            return
        now = self._clock()
        if self._read_at is not None and now - self._read_at < self._ttl:
            return
        self._read_at = now
        try:
            self._stored = {tier: alias for tier, alias in self._store.read().items() if tier in CHAT_TIERS and alias}
        except TierStoreError as error:
            _log.warning("model tier mapping not read, keeping the previous one: %s", error)

    def current(self) -> dict[str, str]:
        """The alias of every tier now."""
        with self._lock:
            self._refresh()
            return {**self.defaults, **self._stored}

    def alias(self, tier: str) -> str:
        if tier not in TIERS:
            raise ValueError(f"unknown tier {tier!r}; use one of {list(TIERS)}")
        return self.current()[tier]

    def invalidate(self) -> None:
        """Read the store again on the next lookup."""
        with self._lock:
            self._read_at = None
