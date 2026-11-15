"""Instant pack marts built as ``pack_admin`` on a running ClickHouse (DECISIONS §4, §9, §11 step 0).

Runs only with ``INSTANT_LIVE_TEST=1``, the admin credentials and ``CLICKHOUSE_PACK_ADMIN_PASSWORD`` of ``.env``.
Two copied tables of a probe source with dates and amounts kept as text become a typed view each and a wide view
that ``pack_admin`` creates as their definer; a table no longer selected loses its views. Everything the test
creates is named after the probe source and dropped at the end.
"""

import os

import pytest

from app.onboarding.marts import apply_marts, mart_tables, plan_marts
from app.sources.inspect import ForeignKey

pytestmark = pytest.mark.skipif(os.environ.get("INSTANT_LIVE_TEST") != "1", reason="needs a running ClickHouse")

PROBE = "instantprobe"


def _client(user: str, password: str):
    clickhouse_connect = pytest.importorskip("clickhouse_connect")
    return clickhouse_connect.get_client(host=os.environ.get("CLICKHOUSE_HOST", "127.0.0.1"),
                                         port=int(os.environ.get("CLICKHOUSE_HTTP_PORT", "8123")),
                                         username=user, password=password)


class _Stored:
    def __init__(self, name, foreign_keys=()):
        self.name, self.mode, self.primary_key, self.foreign_keys = name, "copy", (), foreign_keys


@pytest.fixture
def clients():
    admin = _client(os.environ["CLICKHOUSE_ADMIN_USER"], os.environ["CLICKHOUSE_ADMIN_PASSWORD"])
    admin.command(f"CREATE TABLE raw.{PROBE}__widgets (widget_id Int64, widget_name String) ENGINE = MergeTree ORDER BY widget_id")
    admin.command(f"CREATE TABLE raw.{PROBE}__sales (sale_id Int64, sold_on String, widget_id Int64, amount String) "
                  "ENGINE = MergeTree ORDER BY sale_id")
    admin.command(f"INSERT INTO raw.{PROBE}__widgets VALUES (1, 'Widget 1'), (2, 'Widget 2')")
    admin.command(f"INSERT INTO raw.{PROBE}__sales VALUES (1, '2025-01-02', 1, '10.5'), (2, '2025-02-03', 2, '4'), (3, '', 2, '1')")
    try:
        yield admin, _client("pack_admin", os.environ["CLICKHOUSE_PACK_ADMIN_PASSWORD"])
    finally:
        for view in admin.query(f"SELECT name FROM system.tables WHERE database = 'marts' AND startsWith(name, '{PROBE}__')").result_rows:
            admin.command(f"DROP VIEW IF EXISTS marts.`{view[0]}`")
        admin.command(f"DROP TABLE IF EXISTS raw.{PROBE}__widgets")
        admin.command(f"DROP TABLE IF EXISTS raw.{PROBE}__sales")


def test_pack_admin_builds_typed_and_wide_views_that_read_the_copies(clients):
    admin, pack_admin = clients
    keys = (ForeignKey(("widget_id",), "widgets", ("widget_id",)),)
    tables = mart_tables(pack_admin, PROBE, "postgres", [_Stored("sales", keys), _Stored("widgets")])

    apply_marts(pack_admin, PROBE, plan_marts(PROBE, tables))

    types = dict(admin.query(f"SELECT name, type FROM system.columns WHERE database = 'marts' AND table = '{PROBE}__sales'").result_rows)
    assert types["sold_on"] == "Nullable(Date)" and types["amount"] == "Nullable(Float64)"
    rows = pack_admin.query(f"SELECT sale_id, sold_on, widgets_widget_name FROM marts.{PROBE}__sales__wide ORDER BY sale_id").result_rows
    assert [(row[0], str(row[1]), row[2]) for row in rows] == [(1, "2025-01-02", "Widget 1"), (2, "2025-02-03", "Widget 2"), (3, "None", "Widget 2")]


def test_a_table_no_longer_selected_loses_its_views(clients):
    _, pack_admin = clients
    keys = (ForeignKey(("widget_id",), "widgets", ("widget_id",)),)
    apply_marts(pack_admin, PROBE, plan_marts(PROBE, mart_tables(pack_admin, PROBE, "postgres", [_Stored("sales", keys), _Stored("widgets")])))

    dropped = apply_marts(pack_admin, PROBE, plan_marts(PROBE, mart_tables(pack_admin, PROBE, "postgres", [_Stored("widgets")])))

    assert dropped == [f"{PROBE}__sales", f"{PROBE}__sales__wide"]
