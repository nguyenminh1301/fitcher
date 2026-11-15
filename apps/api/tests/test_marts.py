"""Mart views generated from the selected tables of a source (DECISIONS §4, §11 step 0)."""

from app.onboarding.marts import (
    MartTable, SourceColumn, mart_name, plan_marts, safe_column, text_kinds, text_kinds_query, wide_name,
)
from app.sources.inspect import ForeignKey


def _widgets(live: bool = False) -> MartTable:
    return MartTable(
        name="widgets", relation="`raw`.`shop__widgets`", live=live, primary_key=("widget_id",),
        columns=(SourceColumn("widget_id", "Int64"), SourceColumn("widget_name", "Nullable(String)"),
                 SourceColumn("list_price", "Float64")),
    )


def _sales(**changes) -> MartTable:
    table = MartTable(
        name="sales", relation="`raw`.`shop__sales`", live=False, primary_key=("sale_id",),
        columns=(SourceColumn("sale_id", "Int64"), SourceColumn("sold_on", "Nullable(String)"),
                 SourceColumn("widget_id", "Int64"), SourceColumn("sale_amount", "Decimal(12, 2)")),
        foreign_keys=(ForeignKey(("widget_id",), "widgets", ("widget_id",)),),
        text_kinds={"sold_on": "date"},
    )
    return MartTable(**{**table.__dict__, **changes})


def _by_name(views):
    return {view.name: view for view in views}


def test_each_selected_table_becomes_a_definer_view_named_after_the_source_and_table():
    views = _by_name(plan_marts("shop", [_widgets()]))

    view = views["shop__widgets"]
    assert mart_name("shop", "widgets") == "shop__widgets"
    assert view.statement() == (
        "CREATE OR REPLACE VIEW `marts`.`shop__widgets` DEFINER = CURRENT_USER SQL SECURITY DEFINER AS "
        "SELECT `widget_id`, `widget_name`, `list_price` FROM `raw`.`shop__widgets`"
    )
    assert view.columns == ("widget_id", "widget_name", "list_price")
    assert not view.wide and not view.slow


def test_a_text_column_whose_values_all_parse_is_cast_and_keeps_its_name():
    view = _by_name(plan_marts("shop", [_widgets(), _sales()]))["shop__sales"]

    assert "toDateOrNull(`sold_on`) AS `sold_on`" in view.sql
    assert view.columns == ("sale_id", "sold_on", "widget_id", "sale_amount")


def test_datetime_and_number_text_kinds_are_cast_too():
    table = _sales(text_kinds={"sold_on": "datetime"}, columns=(SourceColumn("sold_on", "String"), SourceColumn("qty", "String")))
    table = MartTable(**{**table.__dict__, "text_kinds": {"sold_on": "datetime", "qty": "number"}, "foreign_keys": ()})

    sql = _by_name(plan_marts("shop", [table]))["shop__sales"].sql

    assert "parseDateTime64BestEffortOrNull(`sold_on`) AS `sold_on`" in sql
    assert "toFloat64OrNull(`qty`) AS `qty`" in sql


def test_a_type_the_pack_cannot_describe_is_cast_to_a_string():
    table = MartTable(name="events", relation="`src_shop`.`events`", live=True,
                      columns=(SourceColumn("tags", "Array(String)"), SourceColumn("address", "IPv4"),
                               SourceColumn("kind", "LowCardinality(String)")))

    sql = _by_name(plan_marts("shop", [table]))["shop__events"].sql

    assert sql == "SELECT toString(`tags`) AS `tags`, toString(`address`) AS `address`, `kind` FROM `src_shop`.`events`"


def test_names_that_are_not_identifiers_are_made_safe_without_any_other_change():
    table = MartTable(name="Order Lines", relation="`src_shop`.`Order Lines`", live=True,
                      columns=(SourceColumn("Line No", "Int32"), SourceColumn("2nd_code", "String"), SourceColumn("Line_No", "Int32")))

    view = plan_marts("shop", [table])[0]

    assert view.name == "shop__order_lines"
    assert view.columns == ("Line_No", "_2nd_code", "Line_No_2")
    assert "`Line No` AS `Line_No`" in view.sql
    assert safe_column("Revenue") == "Revenue"


def test_a_table_with_a_foreign_key_to_a_selected_table_gets_a_wide_view_one_level_deep():
    views = _by_name(plan_marts("shop", [_widgets(), _sales()]))

    wide = views[wide_name("shop", "sales")]
    assert wide.name == "shop__sales__wide" and wide.wide and wide.table == "sales"
    assert wide.columns == (
        "sale_id", "sold_on", "widget_id", "sale_amount", "widgets_widget_name", "widgets_list_price",
    )
    assert wide.sql == (
        "SELECT f.`sale_id` AS `sale_id`, toDateOrNull(f.`sold_on`) AS `sold_on`, f.`widget_id` AS `widget_id`, "
        "f.`sale_amount` AS `sale_amount`, d1.`widget_name` AS `widgets_widget_name`, "
        "d1.`list_price` AS `widgets_list_price` "
        "FROM `raw`.`shop__sales` AS f LEFT JOIN `raw`.`shop__widgets` AS d1 ON f.`widget_id` = d1.`widget_id` "
        "SETTINGS join_use_nulls = 1"
    )
    assert "shop__widgets__wide" not in views


def test_no_wide_view_without_a_single_column_key_to_a_selected_table():
    composite = _sales(foreign_keys=(ForeignKey(("widget_id", "sale_id"), "widgets", ("widget_id", "list_price")),))
    unselected = _sales(foreign_keys=(ForeignKey(("widget_id",), "suppliers", ("supplier_id",)),))

    assert [view.name for view in plan_marts("shop", [_widgets(), composite])] == ["shop__widgets", "shop__sales"]
    assert [view.name for view in plan_marts("shop", [_widgets(), unselected])] == ["shop__widgets", "shop__sales"]


def test_a_wide_view_over_a_table_read_live_is_flagged_slow():
    views = _by_name(plan_marts("shop", [_widgets(live=True), _sales()]))

    assert views["shop__sales__wide"].slow
    assert not views["shop__widgets"].slow


def test_a_dimension_joined_twice_is_prefixed_by_the_key_column_the_second_time():
    table = _sales(
        columns=(*_sales().columns, SourceColumn("gift_widget_id", "Int64")),
        foreign_keys=(ForeignKey(("widget_id",), "widgets", ("widget_id",)),
                      ForeignKey(("gift_widget_id",), "widgets", ("widget_id",))),
    )

    wide = _by_name(plan_marts("shop", [_widgets(), table]))["shop__sales__wide"]

    assert "widgets_widget_name" in wide.columns and "gift_widget_id_widget_name" in wide.columns
    assert "LEFT JOIN `raw`.`shop__widgets` AS d2 ON f.`gift_widget_id` = d2.`widget_id`" in wide.sql


def test_the_text_kinds_query_reads_a_bounded_sample_of_the_string_columns_only():
    sql = text_kinds_query(_sales().relation, _sales().columns, sample_rows=1000)

    assert sql.endswith("FROM (SELECT `sold_on` FROM `raw`.`shop__sales` LIMIT 1000)")
    assert "toDateOrNull(`sold_on`)" in sql
    assert "`sale_id`" not in sql
    assert text_kinds_query("`raw`.`t`", (SourceColumn("n", "Int64"),)) is None


def test_a_string_column_takes_a_kind_only_when_every_sampled_value_parses():
    columns = (SourceColumn("sold_on", "String"), SourceColumn("code", "Nullable(String)"),
               SourceColumn("qty", "String"), SourceColumn("empty", "String"), SourceColumn("n", "Int64"))
    # non-empty, date, datetime, number for each string column in order
    row = (10, 10, 0, 0, 10, 0, 0, 9, 4, 0, 0, 4, 0, 0, 0, 0)

    assert text_kinds(columns, row) == {"sold_on": "date", "qty": "number"}


class _Client:
    """Answers DESCRIBE and the text-kinds sample, lists the marts and records every command."""

    def __init__(self, describe: dict[str, list[tuple[str, str]]], kinds: dict[str, tuple], marts=()):
        self.describe, self.kinds, self.marts = describe, kinds, list(marts)
        self.commands: list[str] = []
        self.queries: list[str] = []

    def query(self, sql, settings=None):
        self.queries.append(sql)
        class _Rows:
            pass
        rows = _Rows()
        if sql.startswith("DESCRIBE TABLE "):
            rows.result_rows = [(name, kind, "", "", "", "", "") for name, kind in self.describe[sql.removeprefix("DESCRIBE TABLE ")]]
        elif sql.startswith("SELECT name FROM system.tables"):
            rows.result_rows = [(name,) for name in self.marts]
        else:
            relation = sql.rsplit(" FROM ", 1)[1].split(" LIMIT ")[0]
            rows.result_rows = [self.kinds[relation]]
        return rows

    def command(self, sql, settings=None):
        self.commands.append(sql)


def _stored(name: str, mode: str = "copy", foreign_keys=()):
    from app.sources.store import StoredTable
    return StoredTable(
        source_id="shop", name=name, kind="table", selected=True, mode=mode, proposed_mode=mode, reason="",
        row_estimate=10, size_bytes=100, columns=(), primary_key=(), foreign_keys=foreign_keys, unusual_columns=(),
        interval_seconds=86400, cursor_column=None, cursor_value=None, next_run_at=None, last_synced_at=None, last_rows=None,
    )


def test_selected_tables_are_described_where_clickhouse_reads_them_and_their_text_sampled():
    from app.onboarding.marts import mart_tables
    client = _Client(
        describe={"`raw`.`shop__sales`": [("sold_on", "Nullable(String)"), ("sale_amount", "Float64")],
                  "`src_shop`.`widgets`": [("widget_id", "Int64")]},
        kinds={"`raw`.`shop__sales`": (5, 5, 0, 0)},
    )
    keys = (ForeignKey(("widget_id",), "widgets", ("widget_id",)),)

    tables = mart_tables(client, "shop", "postgres", [_stored("sales", foreign_keys=keys), _stored("widgets", mode="live")])

    assert [(table.name, table.relation, table.live) for table in tables] == [
        ("sales", "`raw`.`shop__sales`", False), ("widgets", "`src_shop`.`widgets`", True)]
    assert tables[0].text_kinds == {"sold_on": "date"} and tables[0].foreign_keys == keys
    assert tables[1].columns == (SourceColumn("widget_id", "Int64"),)
    assert len([sql for sql in client.queries if "LIMIT" in sql]) == 1


def test_applying_replaces_the_views_and_drops_the_source_marts_no_longer_planned():
    from app.onboarding.marts import apply_marts
    client = _Client({}, {}, marts=["shop__widgets", "shop__refunds", "shop__refunds__wide"])
    views = plan_marts("shop", [_widgets(), _sales()])

    dropped = apply_marts(client, "shop", views)

    assert client.commands[:3] == [view.statement() for view in views]
    assert dropped == ["shop__refunds", "shop__refunds__wide"]
    assert client.commands[3:] == ["DROP VIEW IF EXISTS `marts`.`shop__refunds`", "DROP VIEW IF EXISTS `marts`.`shop__refunds__wide`"]
    assert "engine = 'View'" in client.queries[0] and "startsWith(name, 'shop__')" in client.queries[0]


def test_each_view_knows_its_key_columns_including_the_joined_ones():
    views = _by_name(plan_marts("shop", [_widgets(), _sales()]))

    assert views["shop__widgets"].keys == ("widget_id",)
    assert views["shop__sales"].keys == ("sale_id", "widget_id")
    assert views["shop__sales__wide"].keys == ("sale_id", "widget_id")
