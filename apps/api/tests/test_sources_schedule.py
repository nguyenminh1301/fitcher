"""Due copies run on a schedule inside the api, one at a time per source and never twice across processes."""

from datetime import UTC, datetime, timedelta
import threading

from sources_fixtures import FakeClickHouse
from state_fixtures import new_state

from app.sources.connection import Connection
from app.sources.schedule import SourceScheduler
from app.sources.service import SourceService
from app.sources.store import SourceStore, TableChange

NOW = datetime(2026, 11, 14, 9, 0, tzinfo=UTC)


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


def setup(tmp_path):
    db, _ = new_state(tmp_path)
    store, clickhouse, clock = SourceStore(db), FakeClickHouse(), Clock()
    service = SourceService(store, clickhouse, clock=clock)
    service.create("shop", Connection(kind="postgres", host="db", port=5432, database="erp", user="u", password="p",
                                      schema="public"))
    store.set_tables("shop", [TableChange("orders", selected=True, mode="copy", interval_seconds=3600,
                                          cursor_column="id")])
    return store, clickhouse, service, clock


def test_a_tick_runs_the_due_copy_and_the_next_tick_waits_for_the_interval(tmp_path):
    store, clickhouse, service, clock = setup(tmp_path)
    scheduler = SourceScheduler(service, store, clock=clock)

    assert scheduler.tick() == ["shop"]
    assert store.syncs("shop")[0].started_by == "schedule" and store.syncs("shop")[0].status == "succeeded"
    assert clickhouse.raw["shop__orders"] == 5

    clock.now = NOW + timedelta(minutes=59)
    assert scheduler.tick() == []
    clock.now = NOW + timedelta(hours=1)
    assert scheduler.tick() == ["shop"]
    assert len(store.syncs("shop")) == 2


def test_a_second_scheduler_on_the_same_state_does_not_run_a_source_that_is_syncing(tmp_path):
    store, clickhouse, service, clock = setup(tmp_path)
    store.start_sync("shop", "manual", NOW)
    scheduler = SourceScheduler(service, store, clock=clock)

    assert scheduler.tick() == []
    assert clickhouse.raw == {}


def test_two_schedulers_ticking_together_run_a_due_source_once(tmp_path):
    store, clickhouse, service, clock = setup(tmp_path)
    schedulers = [SourceScheduler(service, SourceStore(store._db), clock=clock) for _ in range(2)]
    ran: list[list[str]] = []

    threads = [threading.Thread(target=lambda s=s: ran.append(s.tick())) for s in schedulers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(len(r) for r in ran) == [0, 1]
    assert len(store.syncs("shop")) == 1


def test_a_failing_sync_does_not_stop_the_scheduler(tmp_path):
    store, clickhouse, service, clock = setup(tmp_path)
    clickhouse.fail_on = r"CREATE TABLE"
    scheduler = SourceScheduler(service, store, clock=clock)

    assert scheduler.tick() == ["shop"]
    assert store.syncs("shop")[0].status == "failed"
    clock.now = NOW + timedelta(hours=1)
    clickhouse.fail_on = None
    assert scheduler.tick() == ["shop"]
    assert store.syncs("shop")[0].status == "succeeded"


def test_an_unexpected_error_in_a_tick_is_logged_and_the_loop_keeps_running(tmp_path, caplog):
    store, _, service, clock = setup(tmp_path)

    def broken(_):
        raise RuntimeError("state unavailable")

    scheduler = SourceScheduler(service, store, clock=clock)
    store.claim_due = broken
    ticked = threading.Event()
    original = scheduler.tick

    def counting():
        try:
            return original()
        finally:
            ticked.set()

    scheduler.tick = counting
    scheduler.start(interval_seconds=0.01)
    assert ticked.wait(5)
    scheduler.stop()

    assert "the scheduled source sync failed" in caplog.text


def test_stopping_ends_the_loop(tmp_path):
    store, _, service, clock = setup(tmp_path)
    scheduler = SourceScheduler(service, store, clock=clock)

    scheduler.start(interval_seconds=0.01)
    scheduler.stop()

    assert not scheduler.running
