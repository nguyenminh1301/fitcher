"""The app state connection: WAL, foreign keys, a busy timeout and one writer at a time.

SQLite connections are not shared between threads, so each thread opens its
own. Reads use that connection directly; every write goes through
``StateDb.write``, which holds one process-wide lock and one immediate
transaction. The data volume must be a local disk: SQLite on a network file
system can corrupt under concurrent access.
"""

from collections.abc import Iterator
from contextlib import contextmanager
import os
from pathlib import Path
import sqlite3
import threading

DEFAULT_DATA_DIR = "/data"
BUSY_TIMEOUT_MS = 5000


def data_dir(env: dict[str, str] | None = None) -> Path:
    return Path((env if env is not None else os.environ).get("FITCHER_DATA_DIR") or DEFAULT_DATA_DIR)


class StateDb:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._lock = threading.RLock()
        self._connections: list[sqlite3.Connection] = []

    def connection(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=BUSY_TIMEOUT_MS / 1000, isolation_level=None, check_same_thread=False)
            conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.execute("PRAGMA foreign_keys = ON")
            self._local.conn = conn
            with self._lock:
                self._connections.append(conn)
        return conn

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn = self.connection()
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")

    def close(self) -> None:
        with self._lock:
            for conn in self._connections:
                conn.close()
            self._connections.clear()
        self._local = threading.local()


_shared: StateDb | None = None
_shared_lock = threading.Lock()


def shared_state() -> StateDb:
    """The process's app state, opened and brought up to date on first use."""
    global _shared
    with _shared_lock:
        if _shared is None:
            from app.state.migrate import apply_pending

            db = StateDb(data_dir() / "app.db")
            apply_pending(db)
            _shared = db
        return _shared


def reset_shared_state() -> None:
    global _shared
    with _shared_lock:
        if _shared is not None:
            _shared.close()
        _shared = None
