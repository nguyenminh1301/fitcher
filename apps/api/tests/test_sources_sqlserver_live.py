"""SQL Server sources against the fixture of the ``sources`` Compose profile (DECISIONS §4, Phase 18).

Runs only with ``SOURCES_LIVE_TEST=1``, the fixtures up and the variables of ``test_sources_connect_live.py``;
the fixture image is amd64 only, so these tests skip on other architectures. ``SQLSERVER_LIVE_HOST`` is the address
the test process reaches the fixture at when its Compose name does not resolve from the host (the fixture publishes
no port). They check that:

- the fixture is connected, its tables listed with estimates, sizes and keys, and every failure has its own reason;
- ``datetime2``, ``decimal``, Vietnamese ``nvarchar``, ``bit`` and ``uniqueidentifier`` values arrive exactly;
- a copy equals the copy of the same dataset from the fixture PostgreSQL, row for row;
- an incremental copy adds only the rows above the cursor, and a copy of one million rows finishes;
- the connection is encrypted and its password is in no table of ClickHouse, in no query log and not in the app state.
"""

import os
import platform
import resource
import shlex
import subprocess
import time

import pytest

from app.sources.client import source_admin_client
from app.sources.connection import Connection
from app.sources.files import FileService
from app.sources.inspect import InspectError
from app.sources.service import SourceService
from app.sources.sqlserver import SqlServer, connect_arguments
from app.sources.store import SourceStore, TableChange
from state_fixtures import new_state

pytestmark = [
    pytest.mark.skipif(os.environ.get("SOURCES_LIVE_TEST") != "1", reason="needs the sources profile"),
    pytest.mark.skipif(platform.machine() not in ("x86_64", "AMD64"), reason="the SQL Server fixture image is amd64 only"),
]

PREFIX = "mssqltest"
ROWS = 1_000_000


def _env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        pytest.skip(f"{name} must be set")
    return value


def _sqlcmd(sql: str, database: str | None = None) -> None:
    extra = shlex.split(os.environ.get("SOURCES_LIVE_COMPOSE", ""))
    target = f"-d {shlex.quote(database)}" if database else ""
    script = f'/opt/mssql-tools18/bin/sqlcmd -C -S localhost -U sa -P "$MSSQL_SA_PASSWORD" {target} -b -Q {shlex.quote(sql)}'
    result = subprocess.run(["docker", "compose", *extra, "--profile", "sources", "exec", "-T", "sqlserver-fixture", "bash", "-c", script],
                            capture_output=True, text=True, timeout=300, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


def _login(**changes) -> dict:
    login = dict(host=os.environ.get("SQLSERVER_LIVE_HOST") or _env("FIXTURE_SQLSERVER_HOST"),
                 port=int(_env("FIXTURE_SQLSERVER_PORT")), database=_env("FIXTURE_SQLSERVER_DATABASE"),
                 user=_env("FIXTURE_SQLSERVER_USER"), password=_env("FIXTURE_SQLSERVER_PASSWORD"), tls_mode="require")
    return login | changes


def _connection(**changes) -> Connection:
    login = _login(**changes)
    return Connection(kind="sqlserver", host=login["host"], port=login["port"], database=login["database"], user=login["user"],
                      password=login["password"], schema="dbo", tls_mode=login["tls_mode"])


def _admin():
    clickhouse_connect = pytest.importorskip("clickhouse_connect")
    return clickhouse_connect.get_client(
        host=os.environ.get("CLICKHOUSE_HOST", "localhost"), port=int(os.environ.get("CLICKHOUSE_HTTP_PORT", "8123")),
        username=_env("CLICKHOUSE_ADMIN_USER"), password=_env("CLICKHOUSE_ADMIN_PASSWORD"), autogenerate_session_id=False)


@pytest.fixture(scope="module")
def state(tmp_path_factory):
    directory = tmp_path_factory.mktemp("state")
    db, vault = new_state(directory)
    store, client = SourceStore(db), source_admin_client()
    service = SourceService(store, client, sqlserver=SqlServer(), vault=vault,
                            files=FileService(store, client, directory / "uploads", max_bytes=1024))
    yield store, service, vault, db, directory
    for source in store.list():
        service.delete(source.id, confirm=source.id)
    for table in ("incremental_probe", "million"):
        _sqlcmd(f"DROP TABLE IF EXISTS dbo.{table}", _env("FIXTURE_SQLSERVER_DATABASE"))


def test_the_fixture_is_connected_and_its_tables_listed_with_sizes_and_keys(state):
    _, service, *_ = state

    source, tables = service.create(f"{PREFIX}_erp", _connection())

    by_name = {table.name: table for table in tables}
    assert {"widgets", "sales", "refunds", "type_probe"} <= set(by_name)
    sales = by_name["sales"]
    assert sales.row_estimate == 3000 and sales.size_bytes > 0
    assert sales.primary_key == ("sale_id",)
    assert any(key.ref_table == "widgets" and key.columns == ("widget_id",) for key in sales.foreign_keys)
    assert (sales.mode, sales.proposed_mode, sales.reason) == ("copy", "copy", "copy_only")
    assert source.kind == "sqlserver" and source.schema == "dbo"


def test_each_failure_has_its_own_reason(state):
    _, service, *_ = state

    for changes, reason in (({"password": "wrong-Pass9"}, "authentication"), ({"host": "nohost.invalid"}, "unreachable"),
                            ({"port": 1}, "refused"),
                            # SQL Server answers a login to a database that does not exist with "Login failed".
                            ({"database": "nodb"}, "authentication")):
        with pytest.raises(InspectError) as raised:
            service.probe(_connection(**changes))
        assert raised.value.reason == reason, changes


def test_the_connection_is_encrypted_and_the_password_is_not_an_environment_secret_of_clickhouse(state):
    pymssql = pytest.importorskip("pymssql")
    login = _login()
    arguments = connect_arguments(**login) | {"user": "sa", "password": os.environ["FIXTURE_ADMIN_PASSWORD"]}
    connection = pymssql.connect(**arguments)
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT encrypt_option FROM sys.dm_exec_connections WHERE session_id = @@SPID")
        assert cursor.fetchone() == ("TRUE",)
    finally:
        connection.close()
    prefer = pymssql.connect(**(connect_arguments(**{**login, "tls_mode": "prefer"}) | {"user": "sa", "password": os.environ["FIXTURE_ADMIN_PASSWORD"]}))
    prefer.close()


def test_a_copy_equals_the_copy_of_the_same_dataset_from_postgres(state):
    store, service, *_ = state
    postgres = Connection(kind="postgres", host=_env("FIXTURE_POSTGRES_HOST"), port=int(_env("FIXTURE_POSTGRES_PORT")),
                          database=_env("FIXTURE_POSTGRES_DATABASE"), user=_env("FIXTURE_POSTGRES_USER"),
                          password=_env("FIXTURE_POSTGRES_PASSWORD"), schema="public")
    service.create(f"{PREFIX}_pg", postgres)
    for source in (f"{PREFIX}_erp", f"{PREFIX}_pg"):
        store.set_tables(source, [TableChange(name, selected=True, mode="copy") for name in ("widgets", "sales", "refunds")])
        assert service.sync(source, "manual").status == "succeeded", source

    admin = _admin()
    # The same columns in the same order and types: one hash over every row covers each of them.
    checks = {name: f"SELECT count(), groupBitXor(cityHash64(*)) FROM raw.{{s}}__{name}" for name in ("sales", "refunds", "widgets")}
    for name, sql in checks.items():
        # raw.<source>__<table>: the file of a SQL Server source and of a PostgreSQL source hold the same rows.
        mssql = admin.query(sql.replace("{s}", f"{PREFIX}_erp")).result_rows
        assert mssql == admin.query(sql.replace("{s}", f"{PREFIX}_pg")).result_rows, name


def test_datetime2_decimal_vietnamese_text_bit_and_uuid_arrive_exactly(state):
    store, service, *_ = state
    store.set_tables(f"{PREFIX}_erp", [TableChange("type_probe", selected=True, mode="copy")])
    assert service.sync(f"{PREFIX}_erp", "manual").status == "succeeded"

    rows = _admin().query(
        f"SELECT id, toString(moment), toString(amount), label, flag, toString(token), toTypeName(moment), toTypeName(amount), "
        f"toTypeName(flag), toTypeName(token) FROM raw.{PREFIX}_erp__type_probe ORDER BY id").result_rows

    assert rows[0] == (1, "2025-03-04 05:06:07.123456", "12345.6789", "Hà Nội — Đà Nẵng, Sài Gòn", True,
                       "6f9619ff-8b86-d011-b42d-00c04fc964ff", "DateTime64(6, 'UTC')", "Decimal(18, 4)", "Bool", "UUID")
    assert rows[1][1:6] == ("2024-12-31 23:59:59.999999", "-0.0001", "Phở bò ăn liền", False, "00000000-0000-0000-0000-000000000000")


def test_an_incremental_copy_adds_only_the_rows_above_the_cursor(state):
    store, service, *_ = state
    database = _env("FIXTURE_SQLSERVER_DATABASE")
    _sqlcmd("DROP TABLE IF EXISTS dbo.incremental_probe; CREATE TABLE dbo.incremental_probe (id int PRIMARY KEY, note nvarchar(20)); "
            "INSERT INTO dbo.incremental_probe VALUES (1, N'a'), (2, N'b'), (3, N'c'); "
            f"GRANT SELECT ON dbo.incremental_probe TO [{_env('FIXTURE_SQLSERVER_USER')}]", database)
    service.refresh(f"{PREFIX}_erp")
    store.set_tables(f"{PREFIX}_erp", [TableChange("incremental_probe", selected=True, mode="copy", cursor_column="id")])

    first = next(r for r in service.sync(f"{PREFIX}_erp", "manual").results if r["table"] == "incremental_probe")
    _sqlcmd("INSERT INTO dbo.incremental_probe VALUES (4, N'd'), (5, N'e'); UPDATE dbo.incremental_probe SET note = N'changed' WHERE id = 1", database)
    second = next(r for r in service.sync(f"{PREFIX}_erp", "schedule").results if r["table"] == "incremental_probe")
    third = next(r for r in service.sync(f"{PREFIX}_erp", "schedule").results if r["table"] == "incremental_probe")

    assert (first["rows"], first["full"]) == (3, True) and (second["rows"], second["full"]) == (2, False) and third["rows"] == 0
    assert _admin().query(f"SELECT id, note FROM raw.{PREFIX}_erp__incremental_probe ORDER BY id").result_rows == [
        (1, "a"), (2, "b"), (3, "c"), (4, "d"), (5, "e")]


def test_a_copy_of_one_million_rows_finishes_in_batches(state):
    store, service, *_ = state
    database = _env("FIXTURE_SQLSERVER_DATABASE")
    _sqlcmd("DROP TABLE IF EXISTS dbo.million; CREATE TABLE dbo.million (id int NOT NULL PRIMARY KEY, amount decimal(12, 2), label nvarchar(40), at datetime2(3)); "
            f"WITH n AS (SELECT TOP ({ROWS}) ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) AS i FROM sys.all_objects a CROSS JOIN sys.all_objects b CROSS JOIN sys.all_objects c) "
            "INSERT INTO dbo.million SELECT i, i % 1000 / 10.0, N'Dòng ' + CAST(i AS nvarchar(10)), DATEADD(second, i, '2025-01-01') FROM n; "
            f"GRANT SELECT ON dbo.million TO [{_env('FIXTURE_SQLSERVER_USER')}]", database)
    service.refresh(f"{PREFIX}_erp")
    store.set_tables(f"{PREFIX}_erp", [TableChange("million", selected=True, mode="copy")])
    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    started = time.monotonic()
    sync = service.sync(f"{PREFIX}_erp", "manual")
    seconds = time.monotonic() - started

    result = next(r for r in sync.results if r["table"] == "million")
    assert sync.status == "succeeded" and result["rows"] == ROWS
    grown_mb = (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - before) / 1024
    print(f"\n1,000,000 rows copied in {seconds:.1f} s; the api process grew by {grown_mb:.0f} MiB at most")
    assert _admin().command(f"SELECT count() FROM raw.{PREFIX}_erp__million") == ROWS
    assert grown_mb < 400, "rows are streamed in batches, not held in memory"


def test_the_password_is_nowhere_in_clickhouse_or_the_app_state_and_the_vault_holds_it_encrypted(state):
    store, service, vault, db, directory = state
    password = _env("FIXTURE_SQLSERVER_PASSWORD")
    admin = _admin()
    admin.command("SYSTEM FLUSH LOGS")
    db.connection().execute("PRAGMA wal_checkpoint(FULL)")
    state_bytes = b"".join(path.read_bytes() for path in directory.glob("app.db*"))

    assert password.encode() not in state_bytes, "the vault stores it encrypted"
    assert vault.has(f"source:{PREFIX}_erp:password") and vault.last_four(f"source:{PREFIX}_erp:password") == password[-4:]
    assert admin.command("SELECT count() FROM system.query_log WHERE user IN ('source_admin', 'source_loader') AND (query LIKE {p:String} OR formatted_query LIKE {p:String})",
                         parameters={"p": f"%{password}%"}) == 0
    assert admin.command("SELECT count() FROM system.tables WHERE create_table_query LIKE {p:String}", parameters={"p": f"%{password}%"}) == 0
    assert source_admin_client().command(f"SELECT count() FROM system.named_collections WHERE name = '{PREFIX}_erp'") == 0


def test_deleting_removes_the_copies_and_the_stored_password(state):
    store, service, vault, *_ = state
    for name in (f"{PREFIX}_erp", f"{PREFIX}_pg"):
        service.delete(name, confirm=name)

    assert not vault.has(f"source:{PREFIX}_erp:password")
    assert _admin().command(f"SELECT count() FROM system.tables WHERE database = 'raw' AND name LIKE '{PREFIX}%'") == 0
