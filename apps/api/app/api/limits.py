"""Limits of the one api process: questions answered at once and the heavy jobs (DECISIONS §3).

fitcher runs a single api process, so both limits live in it. ``QuestionGate``
lets ``limits.concurrent_questions`` questions run at once; the rest wait in
arrival order, and a waiting question whose client left gives up its place.
The per-user rate limit (``rate_limit.py``) still applies before a question
queues. ``one_job`` serialises a source sync, a pack compile and an eval run:
each waits for the one in progress, and a job that starts another inside it
(an instant pack syncs, then compiles) holds the lock it already has.
"""

from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
import threading

class QuestionGate:
    def __init__(self, capacity: Callable[[], int], poll_seconds: float = 0.5):
        self._capacity = capacity
        self._poll = poll_seconds
        self._changed = threading.Condition()
        self._running = 0
        self._waiting: deque[object] = deque()

    def enter(self, on_wait: Callable[[], None], cancelled: Callable[[], bool]) -> bool | None:
        """Wait for a place; ``True`` after waiting, ``False`` at once, ``None`` when ``cancelled`` first."""
        ticket = object()
        waited = False
        with self._changed:
            self._waiting.append(ticket)
            while not (self._waiting[0] is ticket and self._running < max(1, self._capacity())):
                if cancelled():
                    self._waiting.remove(ticket)
                    self._changed.notify_all()
                    return None
                if not waited:
                    waited = True
                    on_wait()
                self._changed.wait(self._poll)
            self._waiting.popleft()
            self._running += 1
            self._changed.notify_all()
        return waited

    def leave(self) -> None:
        with self._changed:
            self._running -= 1
            self._changed.notify_all()

    @property
    def running(self) -> int:
        with self._changed:
            return self._running


_job_lock = threading.RLock()


@contextmanager
def one_job() -> Iterator[None]:
    """Hold the lock that keeps a sync, a compile and an eval run from running at the same time."""
    with _job_lock:
        yield
