import threading

import pytest

from app.state.db import StateDb


def test_database_uses_wal_foreign_keys_and_a_busy_timeout(tmp_path):
    db = StateDb(tmp_path / "nested" / "app.db")
    conn = db.connection()
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] >= 1000


def test_each_thread_gets_its_own_connection(tmp_path):
    db = StateDb(tmp_path / "app.db")
    main = db.connection()
    assert db.connection() is main
    seen = []
    thread = threading.Thread(target=lambda: seen.append(db.connection()))
    thread.start()
    thread.join()
    assert seen[0] is not main


def test_write_commits_on_success_and_rolls_back_on_error(tmp_path):
    db = StateDb(tmp_path / "app.db")
    with db.write() as conn:
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.execute("INSERT INTO t VALUES (1)")
    with pytest.raises(RuntimeError):
        with db.write() as conn:
            conn.execute("INSERT INTO t VALUES (2)")
            raise RuntimeError("stop")
    assert [row[0] for row in db.connection().execute("SELECT x FROM t")] == [1]


def test_writes_from_many_threads_are_serialized(tmp_path):
    db = StateDb(tmp_path / "app.db")
    with db.write() as conn:
        conn.execute("CREATE TABLE t (x INTEGER)")

    def add(n):
        for i in range(20):
            with db.write() as conn:
                conn.execute("INSERT INTO t VALUES (?)", (n * 100 + i,))

    threads = [threading.Thread(target=add, args=(n,)) for n in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert db.connection().execute("SELECT count(*) FROM t").fetchone()[0] == 80
