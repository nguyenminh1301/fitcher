"""Per-user token buckets for ``/ask`` (Phase 7 task 6).

Each user may ask ``per_minute`` questions in a burst; the bucket refills
evenly over a minute. The buckets live in the api process, so each worker
counts on its own; the lab runs one worker.
"""

from collections.abc import Callable
import threading
import time


class RateLimiter:
    def __init__(self, per_minute: int, clock: Callable[[], float] = time.monotonic):
        if per_minute <= 0:
            raise ValueError(f"per_minute must be positive, got {per_minute}")
        self._capacity = float(per_minute)
        self._rate = per_minute / 60.0
        self._clock = clock
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def acquire(self, key: str) -> float:
        """Take one token for ``key``: 0 when granted, else the seconds until the next token."""
        with self._lock:
            now = self._clock()
            tokens, updated = self._buckets.get(key, (self._capacity, now))
            tokens = min(self._capacity, tokens + (now - updated) * self._rate)
            if tokens >= 1:
                self._buckets[key] = (tokens - 1, now)
                return 0.0
            self._buckets[key] = (tokens, now)
            return (1 - tokens) / self._rate
