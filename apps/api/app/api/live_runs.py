"""The questions still running, by conversation.

A run outlives the stream that started it: leaving the chat page, or closing it, closes the stream but the run
goes on and stores its answer, which the conversation shows when it is opened again. Only an explicit stop ends
a run early. A conversation runs one question at a time, so the conversation id names its run.
"""

from collections.abc import Callable
from dataclasses import dataclass
import threading


@dataclass(frozen=True)
class LiveRun:
    user_id: str
    stopped: threading.Event
    cancel: Callable[[], None]


class LiveRuns:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runs: dict[str, LiveRun] = {}

    def add(self, conversation_id: str, run: LiveRun) -> None:
        with self._lock:
            self._runs[conversation_id] = run

    def finish(self, conversation_id: str, run: LiveRun) -> None:
        """Forget the run once it ended; a newer run of the same conversation stays."""
        with self._lock:
            if self._runs.get(conversation_id) is run:
                del self._runs[conversation_id]

    def running(self, user_id: str, conversation_id: str) -> bool:
        with self._lock:
            run = self._runs.get(conversation_id)
            return run is not None and run.user_id == user_id

    def stop(self, user_id: str, conversation_id: str) -> bool:
        """Stop the user's run of the conversation at its next node; False when none is running."""
        with self._lock:
            run = self._runs.get(conversation_id)
        if run is None or run.user_id != user_id:
            return False
        run.stopped.set()
        run.cancel()
        return True


LIVE_RUNS = LiveRuns()
