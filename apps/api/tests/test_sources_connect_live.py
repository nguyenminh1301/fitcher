"""Sources connected from the interface, on a running ClickHouse with the ``sources`` Compose profile (DECISIONS §4, §15).

Runs only with ``SOURCES_LIVE_TEST=1``, the stack up (``docker compose --profile sources up -d --wait``), the admin
credentials, ``CLICKHOUSE_SOURCE_ADMIN_PASSWORD`` and the ``FIXTURE_*`` variables of ``.env``. The service and the
file service run exactly as the api does, as ``source_admin`` against the real named collections and engines:

- the fixture PostgreSQL and MySQL are connected, their tables listed with sizes, keys and a proposed mode;
- one table is attached live and one copied, and an incremental copy picks up only the rows added;
- no password appears in the app state, in ClickHouse's system tables, query log or named collections, or in an
  api response;
- an uploaded CSV and XLSX become ``raw`` tables with the confirmed column types.

The fixture databases are changed only through a throwaway table the tests create and drop with ``docker exec``;
``SOURCES_LIVE_COMPOSE`` holds extra ``docker compose`` arguments (for example ``-p other``) when the stack is not
the default project.
"""

from io import BytesIO
import os
import shlex
import subprocess
import time

from openpyxl import Workbook
import pytest

from app.sources.client import source_admin_client
from app.sources.connection import Connection
from app.sources.files import FileColumn, FileService
from app.sources.service import SourceService
from app.sources.store import SourceStore, TableChange
from state_fixtures import new_state

pytestmark = pytest.mark.skipif(os.environ.get("SOURCES_LIVE_TEST") != "1", reason="needs the sources profile")

PREFIX = "uitest"


def _env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        pytest.skip(f"{name} must be set")
    return value


def _admin():
    clickhouse_connect = pytest.importorskip("clickhouse_connect")
    return clickhouse_connect.get_client(
        host=os.environ.get("CLICKHOUSE_HOST", "localhost"), port=int(os.environ.get("CLICKHOUSE_HTTP_PORT", "8123")),
        username=_env("CLICKHOUSE_ADMIN_USER"), password=_env("CLICKHOUSE_ADMIN_PASSWORD"),
        autogenerate_session_id=False,
    )


def _fixture(service: str, *command: str, stdin: str | None = None) -> str:
    extra = shlex.split(os.environ.get("SOURCES_LIVE_COMPOSE", ""))
    result = subprocess.run(
        ["docker", "compose", *extra, "--profile", "sources", "exec", "-T", service, *command],
        input=stdin, capture_output=True, text=True, timeout=120, check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def _postgres(sql: str) -> str:
    return _fixture("postgres-fixture", "psql", "-U", "postgres", "-d", _env("FIXTURE_POSTGRES_DATABASE"), "-tAc", sql)


def _mysql(sql: str) -> str:
    return _fixture("mysql-fixture", "sh", "-c",
                    f'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE" -NBe {shlex.quote(sql)} 2>/dev/null')


def _connection(kind: str) -> Connection:
    prefix = "FIXTURE_POSTGRES" if kind == "postgres" else "FIXTURE_MYSQL"
    return Connection(kind=kind, host=_env(f"{prefix}_HOST"), port=int(_env(f"{prefix}_PORT")),
                      database=_env(f"{prefix}_DATABASE"), user=_env(f"{prefix}_USER"),
                      password=_env(f"{prefix}_PASSWORD"), schema="public" if kind == "postgres" else None)


@pytest.fixture(scope="module")
def state(tmp_path_factory):
    directory = tmp_path_factory.mktemp("state")
    db, _ = new_state(directory)
    store = SourceStore(db)
    client = source_admin_client()
    files = FileService(store, client, directory / "uploads", max_bytes=10 * 1024 * 1024)
    return store, SourceService(store, client, files=files), files, db, directory


@pytest.fixture(scope="module", autouse=True)
def cleanup(state):
    yield
    store, service, *_ = state
    for source in store.list():
        service.delete(source.id, confirm=source.id)


def test_the_fixture_databases_are_connected_and_their_tables_listed_with_sizes_keys_and_a_mode(state):
    _, service, *_ = state

    postgres, tables = service.create(f"{PREFIX}_postgres", _connection("postgres"))
    mysql, my_tables = service.create(f"{PREFIX}_mysql", _connection("mysql"))

    by_name = {table.name: table for table in tables}
    assert {"widgets", "sales", "refunds"} <= set(by_name)
    sales = by_name["sales"]
    assert sales.row_estimate is not None and 2000 <= sales.row_estimate <= 3000 + 1000 and sales.size_bytes > 0
    assert (sales.proposed_mode, sales.reason) == ("live", "small")
    assert sales.primary_key == ("sale_id",)
    assert any(key.ref_table == "widgets" and key.columns == ("widget_id",) for key in sales.foreign_keys)
    assert {"widgets", "sales", "refunds"} <= {table.name for table in my_tables}
    assert {table.name: table.primary_key for table in my_tables}["sales"] == ("sale_id",)


def test_a_wrong_password_and_a_wrong_host_fail_with_one_reason_each(state):
    _, service, *_ = state
    from app.sources.inspect import InspectError

    for changes, reason in (({"password": "definitely-wrong"}, "authentication"), ({"host": "nohost.invalid"}, "unreachable"),
                            ({"port": 1}, "refused"), ({"database": "nope"}, "database_not_found")):
        with pytest.raises(InspectError) as raised:
            service.probe(Connection(**{**vars(_connection("postgres")), **changes}))
        assert raised.value.reason == reason, changes
    for changes, reason in (({"password": "definitely-wrong"}, "authentication"), ({"host": "nohost.invalid"}, "unreachable")):
        with pytest.raises(InspectError) as raised:
            service.probe(Connection(**{**vars(_connection("mysql")), **changes}))
        assert raised.value.reason == reason, changes


def test_one_table_is_attached_live_and_one_copied(state):
    store, service, *_ = state
    store.set_tables(f"{PREFIX}_postgres", [TableChange("sales", selected=True, mode="live"),
                                            TableChange("refunds", selected=True, mode="copy", interval_seconds=3600)])
    store.set_tables(f"{PREFIX}_mysql", [TableChange("widgets", selected=True, mode="copy")])

    first, second = service.sync(f"{PREFIX}_postgres", "manual"), service.sync(f"{PREFIX}_mysql", "manual")

    assert (first.status, second.status) == ("succeeded", "succeeded"), (first.error, second.error)
    admin = _admin()
    assert admin.command(f"SELECT count() FROM src_{PREFIX}_postgres.sales") == 3000
    assert admin.command(f"SELECT count() FROM raw.{PREFIX}_postgres__refunds") == 300
    assert admin.command(f"SELECT count() FROM raw.{PREFIX}_mysql__widgets") > 0
    assert {r["table"]: (r["mode"], r["rows"]) for r in first.results} == {"sales": ("live", 3000), "refunds": ("copy", 300)}
    refunds = next(table for table in store.tables(f"{PREFIX}_postgres") if table.name == "refunds")
    assert refunds.next_run_at is not None and refunds.last_rows == 300


def test_an_incremental_copy_picks_up_the_rows_added_and_nothing_else(state):
    store, service, *_ = state
    for kind, run, source in (("postgres", _postgres, f"{PREFIX}_inc_pg"), ("mysql", _mysql, f"{PREFIX}_inc_my")):
        table = "incremental_probe"
        run(f"DROP TABLE IF EXISTS {table}")
        run(f"CREATE TABLE {table} (id int primary key, note varchar(20))" if kind == "mysql"
            else f"CREATE TABLE {table} (id int primary key, note text)")
        run(f"INSERT INTO {table} VALUES (1, 'a'), (2, 'b'), (3, 'c')")
        if kind == "postgres":
            run(f"GRANT SELECT ON {table} TO {_env('FIXTURE_POSTGRES_USER')}")
        else:
            run(f"GRANT SELECT ON {_env('FIXTURE_MYSQL_DATABASE')}.{table} TO '{_env('FIXTURE_MYSQL_USER')}'@'%'")
        try:
            service.create(source, _connection(kind))
            store.set_tables(source, [TableChange(table, selected=True, mode="copy", cursor_column="id")])

            first = service.sync(source, "manual")
            assert first.results == [{"table": table, "mode": "copy", "rows": 3, "full": True}], first
            assert store.tables(source)[0].cursor_value == "3"

            run(f"INSERT INTO {table} VALUES (4, 'd'), (5, 'e')")
            run(f"UPDATE {table} SET note = 'changed' WHERE id = 1")
            second = service.sync(source, "schedule")
            assert second.results == [{"table": table, "mode": "copy", "rows": 2, "full": False}], second
            assert _admin().query(f"SELECT id, note FROM raw.{source}__{table} ORDER BY id").result_rows == [
                (1, "a"), (2, "b"), (3, "c"), (4, "d"), (5, "e")], "rows above the cursor only; an update is not seen"

            third = service.sync(source, "schedule")
            assert third.results[0]["rows"] == 0
        finally:
            run(f"DROP TABLE IF EXISTS {table}")
            if any(existing.id == source for existing in store.list()):
                service.delete(source, confirm=source)


def test_no_password_is_in_the_app_state_the_system_tables_the_query_log_or_the_collections(state):
    store, service, files, db, directory = state
    admin = _admin()
    passwords = [_env("FIXTURE_POSTGRES_PASSWORD"), _env("FIXTURE_MYSQL_PASSWORD")]
    db.connection().execute("PRAGMA wal_checkpoint(FULL)")
    state_bytes = b"".join(path.read_bytes() for path in directory.glob("app.db*"))
    admin.command("SYSTEM FLUSH LOGS")

    for password in passwords:
        assert password.encode() not in state_bytes, "the app state holds no password"
        # Every statement of the Sources page runs as source_admin; a check of this test names the password itself.
        assert admin.command(
            "SELECT count() FROM system.query_log WHERE user IN ('source_admin', 'source_loader') "
            "AND (query LIKE {p:String} OR formatted_query LIKE {p:String})", parameters={"p": f"%{password}%"}) == 0, \
            "the query log holds no password"
        assert admin.command("SELECT count() FROM system.query_log WHERE query_kind IN ('Create', 'Alter') "
                             "AND query LIKE '%NAMED COLLECTION%' AND query LIKE {p:String}",
                             parameters={"p": f"%{password}%"}) == 0
        assert admin.command("SELECT count() FROM system.tables WHERE create_table_query LIKE {p:String} OR engine_full LIKE {p:String}",
                             parameters={"p": f"%{password}%"}) == 0
        assert source_admin_client().command("SELECT count() FROM system.named_collections WHERE toString(collection) LIKE {p:String}",
                                             parameters={"p": f"%{password}%"}) == 0
        assert admin.command("SELECT count() FROM system.processes WHERE query LIKE {p:String} AND query NOT LIKE '%system.processes%'",
                             parameters={"p": f"%{password}%"}) == 0
    shown = source_admin_client().query(
        f"SELECT collection FROM system.named_collections WHERE name = '{PREFIX}_postgres'").result_rows
    assert len(shown) == 1 and "[HIDDEN]" in str(shown[0][0])


def test_source_admin_cannot_read_a_collections_secrets(state):
    client = source_admin_client()

    with pytest.raises(Exception, match="SHOW NAMED COLLECTIONS SECRETS"):
        client.query(f"SELECT * FROM postgresql({PREFIX}_postgres, database = 'x', schema = 'public', table = 'y', host = 'elsewhere')")
    rows = client.query(f"SELECT collection FROM system.named_collections WHERE name = '{PREFIX}_postgres'").result_rows
    assert _env("FIXTURE_POSTGRES_PASSWORD") not in str(rows)


def test_a_csv_and_an_xlsx_become_raw_tables_with_the_confirmed_types(state):
    store, service, files, *_ = state
    csv_data = "Mã đơn,Số lượng,Số tiền,Ngày\nA1,2,10.5,2024-01-02\nA2,3,4,2024-01-03\n".encode()
    book = Workbook()
    sheet = book.active
    sheet.append(["id", "name", "qty"])
    sheet.append([1, "Hà Nội", 5])
    sheet.append([2, "Đà Nẵng", 7])
    buffer = BytesIO()
    book.save(buffer)

    uploaded = files.upload("Đơn hàng.csv", BytesIO(csv_data), uploaded_by="test")
    assert [c.name for c in uploaded.columns] == ["Mã đơn", "Số lượng", "Số tiền", "Ngày"]
    types = {c.name: c.type for c in uploaded.columns}
    assert "Int" in types["Số lượng"] and "Float" in types["Số tiền"] and "Date" in types["Ngày"], types
    confirmed = [FileColumn(c.name, "Nullable(Decimal(18, 2))" if c.name == "Số tiền" else c.type) for c in uploaded.columns]
    source = files.load(uploaded.id, f"{PREFIX}_csv", confirmed)

    admin = _admin()
    assert source.kind == "file"
    assert admin.query(f"SELECT count(), sum(`Số tiền`), toTypeName(`Số tiền`) FROM raw.{PREFIX}_csv__{PREFIX}_csv").result_rows == [
        (2, admin.query("SELECT toDecimal64(14.5, 2)").result_rows[0][0], "Nullable(Decimal(18, 2))")]

    workbook = files.upload("Cities.xlsx", BytesIO(buffer.getvalue()), uploaded_by="test")
    assert workbook.format == "xlsx" and workbook.sample == [["1", "Hà Nội", "5"], ["2", "Đà Nẵng", "7"]]
    files.load(workbook.id, f"{PREFIX}_xlsx", [FileColumn(c.name, c.type) for c in workbook.columns])
    assert admin.query(f"SELECT id, name, qty FROM raw.{PREFIX}_xlsx__{PREFIX}_xlsx ORDER BY id").result_rows == [
        (1, "Hà Nội", 5), (2, "Đà Nẵng", 7)]

    assert files.reload(f"{PREFIX}_csv") == 2


def test_deleting_a_source_drops_its_database_its_copies_and_its_collection(state):
    store, service, *_ = state
    admin = _admin()
    for name in (f"{PREFIX}_postgres", f"{PREFIX}_mysql", f"{PREFIX}_csv", f"{PREFIX}_xlsx"):
        service.delete(name, confirm=name)

    assert not [source for source in store.list() if source.id.startswith(PREFIX)]
    assert admin.command(f"SELECT count() FROM system.databases WHERE name LIKE 'src_{PREFIX}%'") == 0
    assert admin.command(f"SELECT count() FROM system.tables WHERE database = 'raw' AND name LIKE '{PREFIX}%'") == 0
    assert source_admin_client().command(f"SELECT count() FROM system.named_collections WHERE name LIKE '{PREFIX}%'") == 0
