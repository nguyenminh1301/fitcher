import re

import pytest

from jobs import refresh_data
from jobs.load_data import LoadError, TableResult
from jobs.lib.manifest import SourceManifest, TableSpec

LOCK = "`data_meta`.`refresh_lock_shop`"


class FakeClient:
    """Records SQL and refresh-log rows; models the lock table and generations."""

    def __init__(self, lock_exists=False, max_generation=0):
        self.lock_exists = lock_exists
        self.max_generation = max_generation
        self.sql = []
        self.rows = []

    def command(self, sql, parameters=None):
        self.sql.append(sql)
        if sql.startswith(f"CREATE TABLE {LOCK}"):
            if self.lock_exists:
                raise Exception("Code: 57. DB::Exception: Table already exists. (TABLE_ALREADY_EXISTS)")
            self.lock_exists = True
        elif sql == f"DROP TABLE IF EXISTS {LOCK}":
            self.lock_exists = False
        elif sql.startswith("SELECT max(generation)"):
            assert parameters == {"source": "shop"}
            return self.max_generation
        return None

    def insert(self, table, data, database=None, column_names=None):
        assert (database, table) == ("data_meta", "refresh_log")
        assert column_names == ["source", "generation", "state", "message"]
        self.sql.append("INSERT refresh_log")
        self.rows.extend((state, generation, message) for _, generation, state, message in data)

    def states(self):
        return [(state, generation) for state, generation, _ in self.rows]


MANIFEST = SourceManifest(
    name="shop",
    hf_repo="example/shop",
    revision="rev1",
    dbt_tag="shop_tag",
    tables=(TableSpec(name="a", file="a.parquet", format="parquet", expected_rows=1),),
)


class Steps:
    def __init__(self, load_error=None, build_code=0):
        self.calls = []
        self.results = []
        self.load_error = load_error
        self.build_code = build_code

    def load(self, manifest, client, data_dir, revision=None):
        self.calls.append(("load", revision))
        if self.load_error:
            raise self.load_error
        return self.results

    def build(self, dbt_tag):
        self.calls.append(("build", dbt_tag))
        return self.build_code


def refresh(client, steps, **kwargs):
    return refresh_data.refresh(MANIFEST, client, "data", load=steps.load, build=steps.build, **kwargs)


def test_success_logs_started_then_completed_with_next_generation():
    client, steps = FakeClient(max_generation=4), Steps()
    assert refresh(client, steps) == 5
    assert client.states() == [("started", 5), ("completed", 5)]
    assert steps.calls == [("load", None), ("build", "shop_tag")]
    assert not client.lock_exists


def test_load_summary_is_reported(capsys):
    steps = Steps()
    steps.results = [TableResult("a", 1, 1)]
    refresh(FakeClient(), steps)
    assert re.search(r"a\s+1\s+1\s+ok", capsys.readouterr().out)


def test_load_summary_is_reported_on_mismatch(capsys):
    steps = Steps(load_error=LoadError("row counts do not match", [TableResult("a", 2, 1)]))
    with pytest.raises(refresh_data.RefreshError):
        refresh(FakeClient(), steps)
    assert re.search(r"a\s+2\s+1\s+MISMATCH", capsys.readouterr().out)


def test_revision_override_reaches_load():
    client, steps = FakeClient(), Steps()
    refresh(client, steps, revision="abc")
    assert steps.calls[0] == ("load", "abc")


def test_log_table_created_if_missing_before_use():
    client = FakeClient()
    refresh(client, Steps())
    touching_log = [s for s in client.sql if "refresh_log" in s]
    assert touching_log[0].startswith("CREATE TABLE IF NOT EXISTS `data_meta`.`refresh_log`")


def test_concurrent_refresh_rejected():
    client, steps = FakeClient(lock_exists=True), Steps()
    with pytest.raises(refresh_data.RefreshError, match="DROP TABLE data_meta.refresh_lock_shop"):
        refresh(client, steps)
    assert client.rows == []
    assert steps.calls == []
    assert client.lock_exists
    assert f"DROP TABLE IF EXISTS {LOCK}" not in client.sql


def test_load_failure_logs_failed_and_skips_build():
    client, steps = FakeClient(), Steps(load_error=LoadError("row counts do not match", []))
    with pytest.raises(refresh_data.RefreshError, match="row counts do not match"):
        refresh(client, steps)
    assert client.states() == [("started", 1), ("failed", 1)]
    assert "row counts do not match" in client.rows[-1][2]
    assert steps.calls == [("load", None)]
    assert not client.lock_exists


def test_build_failure_logs_failed():
    client, steps = FakeClient(), Steps(build_code=1)
    with pytest.raises(refresh_data.RefreshError, match="dbt build"):
        refresh(client, steps)
    assert client.states() == [("started", 1), ("failed", 1)]
    assert not client.lock_exists


def test_unexpected_error_still_logs_failed_and_releases_lock():
    client, steps = FakeClient(), Steps(load_error=RuntimeError("connection reset"))
    with pytest.raises(refresh_data.RefreshError, match="connection reset"):
        refresh(client, steps)
    assert client.states() == [("started", 1), ("failed", 1)]
    assert not client.lock_exists


def test_dbt_build_command_selects_tag_with_upstream(monkeypatch):
    calls = []

    class Done:
        returncode = 3

    monkeypatch.setattr(refresh_data.subprocess, "run", lambda args, check: calls.append(args) or Done())
    assert refresh_data.run_dbt_build("shop_tag") == 3
    assert calls == [
        ["dbt", "build", "--project-dir", "dbt", "--profiles-dir", "dbt", "--select", "+tag:shop_tag"]
    ]


@pytest.fixture
def cli(monkeypatch):
    def setup(client, steps):
        monkeypatch.setattr(refresh_data, "load_manifest", lambda name: MANIFEST)
        monkeypatch.setattr(refresh_data, "admin_client", lambda: client)
        monkeypatch.setattr(refresh_data, "load_source", steps.load)
        monkeypatch.setattr(refresh_data, "run_dbt_build", steps.build)
        return ["--source", "shop"]

    return setup


def test_main_success(cli, capsys):
    assert refresh_data.main(cli(FakeClient(max_generation=4), Steps())) == 0
    assert "generation 5 completed" in capsys.readouterr().out


def test_main_failure(cli, capsys):
    assert refresh_data.main(cli(FakeClient(), Steps(build_code=1))) == 1
    assert "dbt build" in capsys.readouterr().err
