import re

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from jobs import load_data
from jobs.lib import clickhouse
from jobs.lib.manifest import DateRange, ManifestError, SourceManifest, TableSpec


class FakeClient:
    """Records SQL and models table existence and row counts in memory."""

    def __init__(self, existing=(), fail_insert_into=None):
        self.tables = {name: 0 for name in existing}
        self.sql = []
        self.fail_insert_into = fail_insert_into

    def command(self, sql):
        self.sql.append(sql)
        if m := re.fullmatch(r"EXISTS TABLE `(\w+)`\.`(\w+)`", sql):
            return int(f"{m[1]}.{m[2]}" in self.tables)
        if m := re.fullmatch(r"SELECT count\(\) FROM `(\w+)`\.`(\w+)`", sql):
            return self.tables[f"{m[1]}.{m[2]}"]
        if m := re.match(r"CREATE TABLE `(\w+)`\.`(\w+)`", sql):
            self.tables[f"{m[1]}.{m[2]}"] = 0
        elif m := re.fullmatch(r"DROP TABLE (?:IF EXISTS )?`(\w+)`\.`(\w+)`", sql):
            self.tables.pop(f"{m[1]}.{m[2]}", None)
        elif m := re.fullmatch(r"RENAME TABLE `(\w+)`\.`(\w+)` TO `(\w+)`\.`(\w+)`", sql):
            self.tables[f"{m[3]}.{m[4]}"] = self.tables.pop(f"{m[1]}.{m[2]}")
        elif m := re.fullmatch(r"EXCHANGE TABLES `(\w+)`\.`(\w+)` AND `(\w+)`\.`(\w+)`", sql):
            a, b = f"{m[1]}.{m[2]}", f"{m[3]}.{m[4]}"
            self.tables[a], self.tables[b] = self.tables[b], self.tables[a]
        return None

    def insert_arrow(self, table, arrow_table):
        if self.fail_insert_into and table.endswith(f"{self.fail_insert_into}__loading`"):
            raise RuntimeError("insert failed")
        name = table.replace("`", "")
        self.tables[name] += arrow_table.num_rows

    def published(self):
        return [s for s in self.sql if s.startswith(("RENAME", "EXCHANGE"))]


def manifest(*tables):
    return SourceManifest(
        name="shop", hf_repo="example/shop", revision="rev1", dbt_tag="shop", tables=tuple(tables)
    )


def spec(name, rows, **extra):
    return TableSpec(name=name, file=f"{name}.parquet", format="parquet", expected_rows=rows, **extra)


@pytest.fixture
def files(tmp_path):
    """Write Parquet files with a given row count and return a fake download."""
    paths = {}

    def write(name, rows=None, table=None):
        table = table if table is not None else pa.table({"id": [str(i) for i in range(rows)]})
        path = tmp_path / f"{name}.parquet"
        pq.write_table(table, path)
        paths[name + ".parquet"] = path

    def download(source, table, data_dir, revision):
        download.revisions.append(revision)
        return paths[table.file]

    download.revisions = []
    write.download = download
    return write


def run(client, source, files, tmp_path, **kwargs):
    return load_data.load_source(source, client, tmp_path, download=files.download, **kwargs)


def test_clickhouse_type_mapping():
    assert load_data.clickhouse_type(pa.field("a", pa.string())) == "Nullable(String)"
    assert load_data.clickhouse_type(pa.field("a", pa.large_string())) == "Nullable(String)"
    assert load_data.clickhouse_type(pa.field("a", pa.int32())) == "Nullable(Int32)"
    assert load_data.clickhouse_type(pa.field("a", pa.float32())) == "Nullable(Float32)"
    assert load_data.clickhouse_type(pa.field("a", pa.bool_())) == "Nullable(Bool)"
    assert load_data.clickhouse_type(pa.field("a", pa.date32())) == "Nullable(Date32)"
    assert load_data.clickhouse_type(pa.field("a", pa.int64(), nullable=False)) == "Int64"
    with pytest.raises(load_data.LoadError, match="list"):
        load_data.clickhouse_type(pa.field("a", pa.list_(pa.int32())))


def test_first_load_renames_loading_tables(files, tmp_path):
    files("a", 2)
    files("b", 3)
    client = FakeClient()
    results = run(client, manifest(spec("a", 2), spec("b", 3)), files, tmp_path)
    assert [(r.name, r.loaded_rows, r.ok) for r in results] == [("a", 2, True), ("b", 3, True)]
    assert "RENAME TABLE `raw`.`a__loading` TO `raw`.`a`" in client.sql
    assert set(client.tables) == {"raw.a", "raw.b"}
    assert client.tables["raw.b"] == 3


def test_reload_exchanges_and_drops_old(files, tmp_path):
    files("a", 2)
    client = FakeClient(existing=["raw.a"])
    run(client, manifest(spec("a", 2)), files, tmp_path)
    exchange = client.sql.index("EXCHANGE TABLES `raw`.`a__loading` AND `raw`.`a`")
    assert client.sql[exchange + 1] == "DROP TABLE `raw`.`a__loading`"
    assert client.tables == {"raw.a": 2}


def test_row_count_mismatch_publishes_nothing(files, tmp_path):
    files("a", 2)
    client = FakeClient(existing=["raw.a"])
    with pytest.raises(load_data.LoadError) as error:
        run(client, manifest(spec("a", 3)), files, tmp_path)
    assert error.value.results[0].loaded_rows == 2
    assert client.published() == []
    assert client.tables == {"raw.a": 0}


def test_failure_on_last_table_publishes_nothing(files, tmp_path):
    files("a", 2)
    files("b", 3)
    client = FakeClient(fail_insert_into="b")
    with pytest.raises(load_data.LoadError, match="b"):
        run(client, manifest(spec("a", 2), spec("b", 3)), files, tmp_path)
    assert client.published() == []
    assert client.tables == {}


def test_corrupt_download_publishes_nothing(files, tmp_path):
    files("a", 2)
    files("b", 3)
    path = tmp_path / "b.parquet"
    path.write_bytes(path.read_bytes()[:-20])
    client = FakeClient()
    with pytest.raises(load_data.LoadError, match="b"):
        run(client, manifest(spec("a", 2), spec("b", 3)), files, tmp_path)
    assert client.published() == []
    assert client.tables == {}


def test_stale_loading_tables_dropped_first(files, tmp_path):
    files("a", 2)
    client = FakeClient(existing=["raw.a__loading"])
    run(client, manifest(spec("a", 2)), files, tmp_path)
    drop = client.sql.index("DROP TABLE IF EXISTS `raw`.`a__loading`")
    create = next(i for i, s in enumerate(client.sql) if s.startswith("CREATE TABLE `raw`.`a__loading`"))
    assert drop < create
    assert client.tables == {"raw.a": 2}


def test_date_range_filters_half_open(files, tmp_path):
    dates = ["2023-12-31", "2024-01-01", "2024-03-31", "2024-04-01"]
    files("a", table=pa.table({"order_date": dates}))
    table = spec("a", 2, card_rows=4, date_range=DateRange("order_date", "2024-01-01", "2024-04-01"))
    client = FakeClient()
    results = run(client, manifest(table), files, tmp_path)
    assert results[0].loaded_rows == 2
    assert client.tables == {"raw.a": 2}


def test_date_range_on_date_column(files, tmp_path):
    from datetime import date

    dates = [date(2023, 12, 31), date(2024, 1, 1), date(2024, 4, 1)]
    files("a", table=pa.table({"day": pa.array(dates, pa.date32())}))
    table = spec("a", 1, card_rows=3, date_range=DateRange("day", "2024-01-01", "2024-04-01"))
    assert run(FakeClient(), manifest(table), files, tmp_path)[0].loaded_rows == 1


def test_revision_override_used_for_download(files, tmp_path):
    files("a", 1)
    run(FakeClient(), manifest(spec("a", 1)), files, tmp_path)
    run(FakeClient(), manifest(spec("a", 1)), files, tmp_path, revision="abc")
    assert files.download.revisions == ["rev1", "abc"]


def test_download_uses_pinned_revision(monkeypatch, tmp_path):
    calls = []

    def fake_hf_hub_download(**kwargs):
        calls.append(kwargs)
        return str(tmp_path / "a.parquet")

    monkeypatch.setattr(load_data, "hf_hub_download", fake_hf_hub_download)
    path = load_data.download_table(manifest(spec("a", 1)), spec("a", 1), tmp_path, "rev9")
    assert path == tmp_path / "a.parquet"
    assert calls == [
        {
            "repo_id": "example/shop",
            "filename": "a.parquet",
            "repo_type": "dataset",
            "revision": "rev9",
            "local_dir": tmp_path / "shop" / "rev9",
        }
    ]


@pytest.fixture
def cli(monkeypatch, files, tmp_path):
    def setup(expected_rows):
        files("a", 2)
        monkeypatch.setattr(load_data, "load_manifest", lambda name: manifest(spec("a", expected_rows)))
        monkeypatch.setattr(load_data, "admin_client", FakeClient)
        monkeypatch.setattr(load_data, "download_table", files.download)
        return ["--source", "shop", "--data-dir", str(tmp_path)]

    return setup


def test_main_prints_summary_on_success(cli, capsys):
    assert load_data.main(cli(2)) == 0
    out = capsys.readouterr().out
    assert re.search(r"a\s+2\s+2\s+ok", out)


def test_main_prints_summary_on_mismatch(cli, capsys):
    assert load_data.main(cli(5)) == 1
    captured = capsys.readouterr()
    assert re.search(r"a\s+5\s+2\s+MISMATCH", captured.out)
    assert "nothing was published" in captured.err


def test_main_unknown_source_fails(monkeypatch, capsys):
    def missing(name):
        raise ManifestError(f"no manifest for source {name!r}")

    monkeypatch.setattr(load_data, "load_manifest", missing)
    assert load_data.main(["--source", "nope"]) == 1
    assert "no manifest for source 'nope'" in capsys.readouterr().err


def test_admin_client_requires_credentials(monkeypatch):
    monkeypatch.setenv("CLICKHOUSE_ADMIN_USER", "admin")
    monkeypatch.delenv("CLICKHOUSE_ADMIN_PASSWORD", raising=False)
    with pytest.raises(RuntimeError, match="CLICKHOUSE_ADMIN_PASSWORD"):
        clickhouse.admin_client()
