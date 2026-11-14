"""Run the copies that are due, one sync per source at a time (DECISIONS §4, §15).

The scheduler is a thread of the api process. Each tick asks the store which sources have a selected copy table
that is due; the store claims them inside one immediate transaction, so a second api process ticking at the same
moment finds them already syncing and runs nothing. A claimed sync runs the due tables only; a failure is
recorded on the sync and never stops the loop.
"""

from collections.abc import Callable
from datetime import UTC, datetime
import logging
import threading

from app.sources.service import SourceService
from app.sources.store import SourceStore

logger = logging.getLogger(__name__)
DEFAULT_INTERVAL_SECONDS = 30.0


class SourceScheduler:
    def __init__(self, service: SourceService, store: SourceStore, clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self._service = service
        self._store = store
        self._clock = clock
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def tick(self) -> list[str]:
        """Run every due source once, one thread each, and return their names."""
        claims = self._store.claim_due(self._clock())
        threads = []
        for claim in claims:
            thread = threading.Thread(target=self._run, args=(claim,), name=f"scheduled-sync-{claim.source_id}")
            thread.start()
            threads.append(thread)
        for thread in threads:
            thread.join()
        return [claim.source_id for claim in claims]

    def _run(self, claim) -> None:
        try:
            self._service.run(self._store.sync(claim.sync_id), claim.tables)
        except Exception:  # noqa: BLE001 - the sync's own failures are recorded; this is a bug in the sync code
            logger.exception("the scheduled source sync failed")
            self._store.finish_sync(claim.sync_id, "failed", results=[], error="unknown", finished_at=self._clock())

    def _loop(self, interval_seconds: float) -> None:
        self._store.recover_interrupted(self._clock())
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - the app state was unreachable this time; the next tick tries again
                logger.exception("the scheduled source sync failed")
            self._stop.wait(interval_seconds)

    def start(self, interval_seconds: float = DEFAULT_INTERVAL_SECONDS) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, args=(interval_seconds,), name="source-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
