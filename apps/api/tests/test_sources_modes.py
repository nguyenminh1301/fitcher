"""The mode proposed for each table of a source: live below 1 million rows and 1 GB, copy above (DECISIONS §14)."""

import pytest

from app.sources.inspect import ForeignKey, TableInfo
from app.sources.modes import GIB, LIVE_ROW_LIMIT, joined_live_tables, propose


def table(name="orders", rows=1000, size=10_000, kind="table", **fields):
    return TableInfo(name=name, kind=kind, rows=rows, size_bytes=size, **fields)


def test_a_small_table_is_proposed_live():
    proposal = propose(table(rows=999_999, size=GIB - 1))

    assert (proposal.mode, proposal.reason) == ("live", "small")


@pytest.mark.parametrize(("fields", "reason"), [
    (dict(rows=LIVE_ROW_LIMIT, size=10), "rows"),
    (dict(rows=10, size=GIB), "size"),
    (dict(rows=5_000_000, size=5 * GIB), "rows"),
])
def test_a_table_at_or_above_either_limit_is_proposed_as_a_copy(fields, reason):
    proposal = propose(table(**fields))

    assert (proposal.mode, proposal.reason) == ("copy", reason)


def test_a_table_that_reports_only_a_size_or_only_rows_is_judged_by_what_it_reports():
    assert propose(table(rows=None, size=2 * GIB)).mode == "copy"
    assert propose(table(rows=10, size=None)).mode == "live"


def test_a_table_with_no_statistics_is_proposed_live_and_says_so():
    proposal = propose(table(rows=None, size=None))

    assert (proposal.mode, proposal.reason) == ("live", "unknown_size")


def test_a_view_of_the_source_is_proposed_as_a_copy_because_it_runs_its_query_there_on_every_read():
    assert (propose(table(kind="view", rows=None, size=None)).mode, propose(table(kind="view")).reason) == ("copy", "view")


def test_live_tables_that_reference_each_other_are_flagged_as_slow():
    orders = table("orders", foreign_keys=(ForeignKey(("customer_id",), "customers", ("id",)),))
    customers = table("customers")
    audit = table("audit")
    modes = {"orders": "live", "customers": "live", "audit": "live"}

    assert joined_live_tables([orders, customers, audit], modes) == {"orders", "customers"}


def test_a_copied_table_is_never_flagged_because_it_is_joined_at_clickhouse_speed():
    orders = table("orders", foreign_keys=(ForeignKey(("customer_id",), "customers", ("id",)),))
    customers = table("customers")

    assert joined_live_tables([orders, customers], {"orders": "live", "customers": "copy"}) == set()


def test_a_table_that_is_not_selected_is_not_flagged():
    orders = table("orders", foreign_keys=(ForeignKey(("customer_id",), "customers", ("id",)),))

    assert joined_live_tables([orders, table("customers")], {"orders": "live"}) == set()
