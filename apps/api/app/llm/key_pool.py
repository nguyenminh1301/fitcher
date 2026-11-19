"""Which of a provider's keys the gateway tries next (DECISIONS §2).

The keys of one provider are tried round robin: each call starts one key
further than the last, so a provider's free allowances are used evenly. A key
the provider rate-limited rests for its ``Retry-After`` time, or
``COOLDOWN_SECONDS`` when the provider gave none. A key the provider refused
(401 or 403) is not tried again by this process; a replaced key is a new key
with a new id, so it is tried. The state is per process and is lost on restart,
which costs at most one more refused call per key.
"""

from collections.abc import Callable, Sequence
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.llm.gateway import Route

COOLDOWN_SECONDS = 60.0
# The longest rest a provider's Retry-After can impose; a larger value is a daily limit and the
# chain's next model answers meanwhile.
MAX_COOLDOWN_SECONDS = 3600.0


class KeyPool:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._next: dict[str, int] = {}
        self._resting: dict[tuple[str, str], float] = {}
        self._refused: set[tuple[str, str]] = set()

    def _usable(self, route: "Route", now: float) -> bool:
        if route.key_id is None:
            return True
        key = (route.provider, route.key_id)
        return key not in self._refused and self._resting.get(key, 0.0) <= now

    def order(self, routes: Sequence["Route"]) -> list["Route"]:
        """The routes of one provider's model to try, starting one key past the previous call's start."""
        if len(routes) <= 1:
            now = self._clock()
            return [route for route in routes if self._usable(route, now)]
        provider = routes[0].provider
        with self._lock:
            start = self._next.get(provider, 0) % len(routes)
            self._next[provider] = start + 1
            now = self._clock()
            rotated = [*routes[start:], *routes[:start]]
            return [route for route in rotated if self._usable(route, now)]

    def rest(self, route: "Route", seconds: float | None) -> None:
        """The provider rate-limited this key: do not use it for ``seconds`` (or the default)."""
        if route.key_id is None:
            return
        wait = min(max(seconds if seconds is not None else COOLDOWN_SECONDS, 1.0), MAX_COOLDOWN_SECONDS)
        with self._lock:
            self._resting[(route.provider, route.key_id)] = self._clock() + wait

    def refuse(self, route: "Route") -> None:
        """The provider refused this key: do not use it again."""
        if route.key_id is not None:
            with self._lock:
                self._refused.add((route.provider, route.key_id))


SHARED = KeyPool()
