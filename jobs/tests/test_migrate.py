from types import SimpleNamespace

import pytest

from app.state.migrate import MigrationError
from jobs import apply_log_schema, migrate


class FakeClickHouse:
    """Records commands and keeps the rows of data_meta.schema_changes."""

    def __init__(self, recorded=()):
        self.commands = []
        self.rows = [[n, f"c{n}"] for n in recorded]

    def command(self, sql):
        self.commands.append(sql)

    def query(self, sql):
        assert "data_meta.schema_changes" in sql
        return SimpleNamespace(result_rows=[(row[0],) for row in self.rows])

    def insert(self, table, data, column_names):
        assert table == "data_meta.schema_changes" and column_names == ["number", "name"]
        self.rows.extend(data)


def shipped():
    return [c.number for c in migrate.discover(migrate.CLICKHOUSE_CHANGES_DIR)]


def test_shipped_clickhouse_changes_keep_the_original_files_in_order():
    names = [c.label for c in migrate.discover(migrate.CLICKHOUSE_CHANGES_DIR)]
    assert names == ["0001_databases", "0002_agent_logs", "0003_model_tiers", "0004_documents"]


def test_fresh_volume_applies_and_records_every_change_then_nothing():
    client = FakeClickHouse()
    assert migrate.apply_clickhouse(client) == shipped()
    assert [row[0] for row in client.rows] == shipped()
    commands = len(client.commands)
    assert migrate.apply_clickhouse(client) == []
    assert len(client.commands) == commands + len(migrate.REGISTRY_STATEMENTS)


def test_existing_volume_is_brought_up_to_date_with_the_same_statements():
    fresh, existing = FakeClickHouse(), FakeClickHouse()
    migrate.apply_clickhouse(fresh)
    migrate.apply_clickhouse(existing)  # a volume the entrypoint created, then recorded by the first run
    assert fresh.commands == existing.commands
    assert all(
        statement.startswith(("CREATE ", "ALTER TABLE ", "SYSTEM FLUSH LOGS"))
        and ("IF NOT EXISTS" in statement or statement.startswith("SYSTEM"))
        for statement in fresh.commands
    )


def test_clickhouse_that_records_a_newer_change_is_refused():
    client = FakeClickHouse(recorded=[*shipped(), max(shipped()) + 1])
    with pytest.raises(MigrationError, match="newer"):
        migrate.apply_clickhouse(client)


def test_a_failing_clickhouse_change_is_not_recorded(tmp_path):
    (tmp_path / "0001_bad.sql").write_text("CREATE TABLE x (a UInt8);", encoding="utf-8")

    class Failing(FakeClickHouse):
        def command(self, sql):
            if sql.startswith("CREATE TABLE x"):
                raise RuntimeError("boom")
            super().command(sql)

    client = Failing()
    with pytest.raises(MigrationError, match="0001_bad"):
        migrate.apply_clickhouse(client, tmp_path)
    assert client.rows == []


def test_main_reports_missing_credentials(monkeypatch, capsys):
    monkeypatch.delenv("CLICKHOUSE_ADMIN_USER", raising=False)
    monkeypatch.delenv("CLICKHOUSE_ADMIN_PASSWORD", raising=False)
    assert migrate.main([]) == 1
    assert "CLICKHOUSE_ADMIN_USER" in capsys.readouterr().err


def test_main_migrates_both_stores_and_a_second_run_applies_nothing(monkeypatch, tmp_path, capsys):
    client = FakeClickHouse()
    monkeypatch.setattr(migrate, "admin_client", lambda: client)
    monkeypatch.setenv("FITCHER_DATA_DIR", str(tmp_path))
    assert migrate.main([]) == 0
    first = capsys.readouterr().out
    assert "ClickHouse: applied 0001" in first and "App state: applied 0001" in first
    assert (tmp_path / "app.db").exists()
    assert migrate.main([]) == 0
    second = capsys.readouterr().out
    assert "ClickHouse: up to date." in second and "App state: up to date." in second


def test_the_old_job_name_runs_the_migration():
    assert apply_log_schema.main is migrate.main
