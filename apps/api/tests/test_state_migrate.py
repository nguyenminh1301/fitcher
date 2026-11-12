import pytest

from app.state import migrate
from app.state.db import StateDb


def write_changes(directory, **files):
    directory.mkdir(parents=True, exist_ok=True)
    for name, sql in files.items():
        (directory / f"{name}.sql").write_text(sql, encoding="utf-8")
    return directory


def applied(db):
    return [tuple(r) for r in db.connection().execute("SELECT number, name FROM schema_changes ORDER BY number")]


def test_shipped_changes_are_numbered_without_gaps():
    changes = migrate.discover(migrate.CHANGES_DIR)
    assert [c.number for c in changes] == list(range(1, len(changes) + 1))
    assert [c.name for c in changes][:3] == ["settings", "secrets", "setup"]


def test_applies_pending_changes_in_order_and_records_them(tmp_path):
    db = StateDb(tmp_path / "app.db")
    directory = write_changes(tmp_path / "c", **{"0001_a": "CREATE TABLE a (x INTEGER);", "0002_b": "CREATE TABLE b (y INTEGER);"})
    assert migrate.apply_pending(db, directory) == [1, 2]
    assert applied(db) == [(1, "a"), (2, "b")]
    assert migrate.apply_pending(db, directory) == []


def test_applies_only_changes_added_later(tmp_path):
    db = StateDb(tmp_path / "app.db")
    directory = write_changes(tmp_path / "c", **{"0001_a": "CREATE TABLE a (x INTEGER);"})
    migrate.apply_pending(db, directory)
    write_changes(directory, **{"0002_b": "CREATE TABLE b (y INTEGER);"})
    assert migrate.apply_pending(db, directory) == [2]


def test_a_failing_change_leaves_no_trace_of_itself(tmp_path):
    db = StateDb(tmp_path / "app.db")
    directory = write_changes(tmp_path / "c", **{
        "0001_a": "CREATE TABLE a (x INTEGER);",
        "0002_bad": "CREATE TABLE b (y INTEGER);\nINSERT INTO missing VALUES (1);",
    })
    with pytest.raises(migrate.MigrationError, match="0002_bad"):
        migrate.apply_pending(db, directory)
    assert applied(db) == [(1, "a")]
    tables = {r[0] for r in db.connection().execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "b" not in tables


def test_refuses_a_store_written_by_a_newer_version(tmp_path):
    db = StateDb(tmp_path / "app.db")
    directory = write_changes(tmp_path / "c", **{"0001_a": "CREATE TABLE a (x INTEGER);", "0002_b": "CREATE TABLE b (y INTEGER);"})
    migrate.apply_pending(db, directory)
    older = write_changes(tmp_path / "older", **{"0001_a": "CREATE TABLE a (x INTEGER);"})
    with pytest.raises(migrate.MigrationError, match="newer"):
        migrate.apply_pending(db, older)


def test_rejects_gaps_and_duplicate_numbers(tmp_path):
    gap = write_changes(tmp_path / "gap", **{"0001_a": "SELECT 1;", "0003_c": "SELECT 1;"})
    with pytest.raises(migrate.MigrationError, match="gap"):
        migrate.discover(gap)
    dup = write_changes(tmp_path / "dup", **{"0001_a": "SELECT 1;", "0001_b": "SELECT 1;"})
    with pytest.raises(migrate.MigrationError, match="twice"):
        migrate.discover(dup)


def test_shipped_changes_create_the_state_tables(tmp_path):
    db = StateDb(tmp_path / "app.db")
    migrate.apply_pending(db)
    tables = {r[0] for r in db.connection().execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"schema_changes", "settings", "secrets", "setup_steps"} <= tables
