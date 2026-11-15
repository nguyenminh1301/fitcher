"""Run the copies that are due, one sync per source at a time (DECISIONS §4, §15).

The scheduler is a thread of the api process. Each tick asks the store which sources have a selected copy table
that is due; the store claims them inside one immediate transaction, so a second api process ticking at the same
moment finds them already syncing and runs nothing. A claimed sync runs the due tables only; a failure is
recorded on the sync and never stops the loop.

A source read live is never copied, so its catalog is read again once a day instead: the Sources page then shows
the columns an instant pack's tables gained, lost or retyped (app/onboarding/drift.py).
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
import logging
import threading

from app.sources.service import SourceService
from app.sources.store import SourceStore

logger = logging.getLogger(__name__)
DEFAULT_INTERVAL_SECONDS = 30.0
LIVE_CATALOG_EVERY = timedelta(days=1)


class SourceScheduler:
    def __init__(self, service: SourceService, store: SourceStore, clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self._service = service
        self._store = store
        self._clock = clock
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # When each source with live tables last had its catalog read; kept in this process only.
        self._catalog_read: dict[str, datetime] = {}

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
        self._read_live_catalogs()
        return [claim.source_id for claim in claims]

    def _read_live_catalogs(self) -> None:
        now = self._clock()
        for source in self._store.list():
            if not any(table.selected and table.mode == "live" for table in self._store.tables(source.id)):
                continue
            last = self._catalog_read.get(source.id)
            if last is not None and now - last < LIVE_CATALOG_EVERY:
                continue
            self._catalog_read[source.id] = now
            try:
                self._service.refresh(source.id)
            except Exception:  # noqa: BLE001 - an unreachable source is read again the next day
                logger.warning("the catalog of source %s could not be read", source.id)

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
