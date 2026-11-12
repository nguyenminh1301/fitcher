"""Data sources on a running ClickHouse with the ``sources`` Compose profile (DECISIONS §4).

Runs only with ``SOURCES_LIVE_TEST=1``, the fixtures up
(``docker compose --profile sources up -d --wait``), the admin credentials,
``CLICKHOUSE_SOURCES_PASSWORD`` and the ``FIXTURE_*`` variables of ``.env``,
from the repository root so dbt finds its project. Each test syncs a fixture
source with ``jobs.sync_sources`` and builds the fixture_widgets marts with
dbt, exactly as ``jobs.refresh_data`` does:

- every kind and mode yields the same marts, row for row;
- column grants, row policies and aggregate-only views of the minimal test
  pack behave the same on marts that are views over live sources as on
  copied data, and an agent role reads neither ``src_*`` nor ``raw``;
- no role but source_loader holds a grant on ``src_*``;
- no fixture password appears in DDL, the query log, dbt's files or
  ``system.named_collections``.

The probe pack's ClickHouse objects use the pack name ``sourceprobe`` and are
dropped again at the end.
"""

import dataclasses
import os
from pathlib import Path

import pytest

from app.packs.compiler import approved_pack
from app.packs.loader import load_pack
from app.packs.models import AggregateOnly, DatasetGrant
from app.packs.policy_compiler import Names, agent_password, apply_policies

pytestmark = pytest.mark.skipif(os.environ.get("SOURCES_LIVE_TEST") != "1", reason="needs the sources profile")

ROOT = Path(__file__).resolve().parents[3]
FIXTURE_PACK = Path(__file__).parent / "fixtures" / "packs" / "minimal"
SOURCES = ("fixture_postgres", "fixture_mysql", "fixture_mongodb", "fixture_files")
PROBE = "sourceprobe"
SECRET = "sourceprobe-secret"
FILTERED_WIDGET = "Widget 01"
MIN_GROUP = 80

# Every result the equivalence test compares; the fixture dataset holds 3,000 sales and 300 refunds.
CHECKS = {
    "columns": "SELECT table, name, type FROM system.columns WHERE database = 'marts' "
    "AND table IN ('widget_sales', 'widget_refunds') ORDER BY table, position",
    "sales": "SELECT count(), sum(sale_amount), sum(widget_count), min(sold_on), max(sold_on) FROM marts.widget_sales",
    "refunds": "SELECT count(), sum(refund_total), min(refunded_on), max(refunded_on) FROM marts.widget_refunds",
    "rows": "SELECT groupBitXor(cityHash64(*)) FROM marts.widget_sales",
    "refund_rows": "SELECT groupBitXor(cityHash64(*)) FROM marts.widget_refunds",
    "by_group": "SELECT region, widget_category, count(), sum(sale_amount) FROM marts.widget_sales "
    "GROUP BY region, widget_category ORDER BY region, widget_category",
    "by_month": "SELECT toStartOfMonth(sold_on) AS month, sum(sale_amount) FROM marts.widget_sales "
    "GROUP BY month ORDER BY month",
}


def _client(user: str, password: str):
    clickhouse_connect = pytest.importorskip("clickhouse_connect")
    return clickhouse_connect.get_client(
        host=os.environ.get("CLICKHOUSE_HOST", "localhost"),
        port=int(os.environ.get("CLICKHOUSE_HTTP_PORT", "8123")),
        username=user, password=password, autogenerate_session_id=False,
    )


class Admin:
    def __init__(self, client):
        self.client = client

    def query(self, sql, settings=None):
        return self.client.query(sql, settings=settings).result_rows

    def command(self, sql):
        self.client.command(sql)


@pytest.fixture(scope="module")
def admin():
    return Admin(_client(os.environ["CLICKHOUSE_ADMIN_USER"], os.environ["CLICKHOUSE_ADMIN_PASSWORD"]))


@pytest.fixture(scope="module")
def build():
    """Sync one fixture source in one mode and build the fixture marts over it."""
    from jobs.lib.clickhouse import sources_client
    from jobs.lib.source_manifest import load_manifest
    from jobs.refresh_data import run_dbt_build
    from jobs.sync_sources import sync_source

    os.environ.setdefault("CLICKHOUSE_HOST", "localhost")
    previous = Path.cwd()
    os.chdir(ROOT)
    loader = sources_client()

    def run(name: str, mode: str):
        manifest = dataclasses.replace(load_manifest(name), mode=mode)
        assert all(result.ok for result in sync_source(manifest, loader))
        assert run_dbt_build(manifest) == 0, f"dbt build over {name} in {mode} mode failed"

    yield run
    os.chdir(previous)


def _checks(admin) -> dict:
    return {name: admin.query(sql) for name, sql in CHECKS.items()}


def test_every_kind_and_mode_yields_the_same_marts(build, admin):
    build("fixture_postgres", "copy")
    reference = _checks(admin)
    assert reference["sales"][0][0] == 3000 and reference["refunds"][0][0] == 300

    differences = []
    for name in SOURCES:
        for mode in ("copy", "live"):
            build(name, mode)
            engine = admin.query("SELECT engine FROM system.tables WHERE database = 'marts' AND name = 'widget_sales'")
            assert engine == [("View" if mode == "live" else "MergeTree",)]
            found = _checks(admin)
            differences += [f"{name} {mode}: {check}" for check in CHECKS if found[check] != reference[check]]
    assert differences == []


def _probe_pack():
    pack = approved_pack(load_pack(FIXTURE_PACK, schema_dir=ROOT / "packs" / "_schema"))
    base = pack.policies.roles[0]
    columns = ["sale_ref", "sold_on", "widget_name", "sale_amount"]
    roles = [
        base.model_copy(update={"id": "reader", "datasets": [DatasetGrant(dataset="widget_sales", columns=columns)]}),
        base.model_copy(update={"id": "filtered", "datasets": [
            DatasetGrant(dataset="widget_sales", columns=columns, row_filter=f"widget_name = '{FILTERED_WIDGET}'"),
        ]}),
        base.model_copy(update={"id": "summary", "datasets": [
            DatasetGrant(
                dataset="widget_sales", columns=["widget_name"],
                aggregate_only=AggregateOnly(metrics=["widget_revenue"], min_group_size=MIN_GROUP),
            ),
        ]}),
    ]
    return pack.model_copy(update={"name": PROBE, "policies": pack.policies.model_copy(update={"roles": roles})})


@pytest.fixture
def probe_pack(admin):
    pack = _probe_pack()
    yield pack
    empty = pack.model_copy(update={"policies": pack.policies.model_copy(update={"roles": []})})
    apply_policies(empty, admin, SECRET)


def _as_role(role: str):
    user = Names(PROBE).user(role)
    return _client(user, agent_password(SECRET, user))


def _denied(client, sql: str) -> bool:
    try:
        client.query(sql)
    except Exception as error:  # noqa: BLE001 - the error text names the refusal
        if "ACCESS_DENIED" in str(error):
            return True
        raise
    return False


def _rbac_outcome(admin, live_database: str) -> dict:
    reader, filtered, summary = _as_role("reader"), _as_role("filtered"), _as_role("summary")
    view = f"marts.`{Names(PROBE).view('summary', 'widget_sales')}`"
    groups, smallest = summary.query(f"SELECT count(), min(row_count) FROM {view}").result_rows[0]
    widgets = admin.query("SELECT uniqExact(widget_name) FROM marts.widget_sales")[0][0]
    expected = admin.query(f"SELECT count() FROM marts.widget_sales WHERE widget_name = '{FILTERED_WIDGET}'")[0][0]
    return {
        "granted column": reader.query("SELECT sum(sale_amount) FROM marts.widget_sales").result_rows[0][0] > 0,
        "ungranted column denied": _denied(reader, "SELECT region FROM marts.widget_sales LIMIT 1"),
        "live source denied": _denied(reader, f"SELECT count() FROM `{live_database}`.`sales`"),
        "raw denied": _denied(reader, "SELECT count() FROM raw.stg_fixture_widgets__sales"),
        "row policy": filtered.query("SELECT count() FROM marts.widget_sales").result_rows[0][0] == expected > 0,
        "small groups hidden": smallest >= MIN_GROUP and 0 < groups < widgets,
        "aggregate role denied the mart": _denied(summary, "SELECT count() FROM marts.widget_sales"),
    }


@pytest.mark.parametrize(("name", "mode"), [(name, "live") for name in SOURCES] + [("fixture_postgres", "copy")])
def test_rbac_holds_on_live_marts_as_on_copied_data(build, admin, probe_pack, name, mode):
    from jobs.lib.source_engines import live_database
    from jobs.lib.source_manifest import load_manifest

    if mode == "copy":
        # Defines src_<source>, so the live-source denial is checked against a real table.
        build(name, "live")
    build(name, mode)
    apply_policies(probe_pack, admin, SECRET)

    outcome = _rbac_outcome(admin, live_database(load_manifest(name)))
    assert outcome == dict.fromkeys(outcome, True)


def test_no_role_but_source_loader_is_granted_src_databases(build, admin):
    build("fixture_postgres", "live")
    grants = admin.query(
        "SELECT user_name, role_name, access_type, database, table FROM system.grants "
        "WHERE startsWith(database, 'src_') AND ifNull(user_name, '') != 'source_loader'"
    )
    assert grants == []
    agent_users = admin.query("SELECT name FROM system.users WHERE startsWith(name, 'fitcher_agent__')")
    agent_roles = admin.query("SELECT name FROM system.roles WHERE startsWith(name, 'fitcher_role__')")
    widened = admin.query(
        "SELECT user_name, role_name, access_type FROM system.grants "
        "WHERE (startsWith(ifNull(role_name, ''), 'fitcher_role__') OR startsWith(ifNull(user_name, ''), 'fitcher_agent__')) "
        "AND (database IS NULL OR database IN ('raw') OR startsWith(database, 'src_'))"
    )
    assert widened == [], f"agent grants beyond marts for {len(agent_users)} users and {len(agent_roles)} roles"


def _fixture_passwords() -> list[str]:
    names = [f"FIXTURE_{kind}_PASSWORD" for kind in ("POSTGRES", "MYSQL", "MONGODB", "FILES")]
    passwords = [os.environ.get(name, "") for name in names]
    if not all(passwords):
        pytest.skip("every FIXTURE_*_PASSWORD must be set")
    return passwords


def test_no_credential_appears_in_ddl_logs_or_system_tables(build, admin):
    passwords = _fixture_passwords()
    for name in SOURCES:
        build(name, "copy")
        build(name, "live")
    admin.command("SYSTEM FLUSH LOGS")

    texts = [row[0] for row in admin.query("SELECT create_table_query FROM system.tables")]
    texts += [row[0] for row in admin.query("SELECT engine_full FROM system.tables")]
    texts += [row[0] for row in admin.query("SELECT engine_full FROM system.databases")]
    # Only the queries that name a source; reading every query would also read this test's own reads.
    texts += [row[0] for row in admin.query(
        "SELECT query FROM system.query_log WHERE event_date >= yesterday() "
        "AND (query ILIKE '%fixture\\_%' OR query ILIKE '%src\\_%')"
    )]
    loader = _client("source_loader", os.environ["CLICKHOUSE_SOURCES_PASSWORD"])
    collections = loader.query("SELECT name, toString(collection) FROM system.named_collections").result_rows
    assert {row[0] for row in collections} >= set(SOURCES)
    texts += [row[1] for row in collections]
    for directory in (os.environ.get("DBT_LOG_PATH"), os.environ.get("DBT_TARGET_PATH"), ROOT / "dbt" / "logs", ROOT / "dbt" / "target"):
        if directory and Path(directory).is_dir():
            texts += [path.read_text(encoding="utf-8", errors="ignore") for path in Path(directory).rglob("*") if path.is_file()]

    leaks = [index for index, text in enumerate(texts) if any(password in text for password in passwords)]
    assert leaks == [], f"{len(leaks)} texts contain a fixture password"
