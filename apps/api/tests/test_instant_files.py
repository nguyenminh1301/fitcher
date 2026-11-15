"""The deterministic files of an instant pack, written before the drafter fills them (DECISIONS §5, §11 step 0)."""

from conftest import SCHEMA_DIR
import yaml

from app.onboarding.instant_files import READER_ROLE, dataset_items, write_pack_files
from app.onboarding.marts import MartTable, SourceColumn, plan_marts
from app.packs.loader import load_pack
from app.sources.inspect import ForeignKey

WIDGETS = MartTable(name="widgets", relation="`raw`.`shop__widgets`", live=False, primary_key=("widget_id",),
                    columns=(SourceColumn("widget_id", "Int64"), SourceColumn("widget_name", "String"),
                             SourceColumn("launched_on", "Date")))
SALES = MartTable(name="sales", relation="`raw`.`shop__sales`", live=False, primary_key=("sale_id",),
                  columns=(SourceColumn("sale_id", "Int64"), SourceColumn("sold_on", "String"),
                           SourceColumn("widget_id", "Int64"), SourceColumn("sale_amount", "Float64"),
                           SourceColumn("paid", "Bool")),
                  foreign_keys=(ForeignKey(("widget_id",), "widgets", ("widget_id",)),), text_kinds={"sold_on": "date"})
REFUNDS = MartTable(name="refunds", relation="`raw`.`shop__refunds`", live=False,
                    columns=(SourceColumn("refund_amount", "Float64"),))


def _column(kind: str, distinct: int) -> dict:
    return {"type": kind, "distinct": distinct}


PROFILE = {
    "tables": {
        "shop__widgets": {"rows": 3, "columns": {"widget_id": _column("number", 3), "widget_name": _column("string", 3),
                                                 "launched_on": _column("date", 2)}},
        "shop__sales": {"rows": 9, "columns": {"sale_id": _column("number", 9), "sold_on": _column("date", 4),
                                               "widget_id": _column("number", 3), "sale_amount": _column("number", 9),
                                               "paid": _column("boolean", 2)}},
        "shop__sales__wide": {"rows": 9, "columns": {
            "sale_id": _column("number", 9), "sold_on": _column("date", 4), "widget_id": _column("number", 3),
            "sale_amount": _column("number", 9), "paid": _column("boolean", 2),
            "widgets_widget_name": _column("string", 3), "widgets_launched_on": _column("date", 2)}},
        "shop__refunds": {"rows": 2, "columns": {"refund_amount": _column("number", 2)}},
    },
    "join_candidates": [],
}
VIEWS = plan_marts("shop", [WIDGETS, SALES, REFUNDS])


def _by_id(items):
    return {item["id"]: item for item in items}


def test_numbers_are_measures_dates_time_and_keys_and_text_dimensions():
    sales = _by_id(dataset_items(VIEWS, PROFILE))["shop__sales"]

    roles = {column["name"]: (column["type"], column["role"]) for column in sales["columns"]}
    assert roles == {"sale_id": ("number", "dimension"), "sold_on": ("date", "time"), "widget_id": ("number", "dimension"),
                     "sale_amount": ("number", "measure"), "paid": ("boolean", "dimension")}
    assert sales["time_column"] == "sold_on" and sales["allowed_roles"] == [READER_ROLE]
    assert sales["status"] == "draft" and sales["evidence"] == [{"kind": "profile", "ref": "shop__sales"}]


def test_a_string_column_with_few_values_is_indexed_and_a_key_never_is():
    widgets = _by_id(dataset_items(VIEWS, PROFILE))["shop__widgets"]

    indexed = [column["name"] for column in widgets["columns"] if column.get("indexable")]
    assert indexed == ["widget_name"]


def test_the_wide_view_comes_first_and_keeps_its_own_time_column():
    items = dataset_items(VIEWS, PROFILE)

    assert [item["id"] for item in items] == ["shop__sales__wide", "shop__widgets", "shop__sales"]
    assert items[0]["time_column"] == "sold_on"


def test_a_view_without_a_time_column_gets_no_dataset():
    assert "shop__refunds" not in _by_id(dataset_items(VIEWS, PROFILE))


def test_the_written_pack_is_valid_with_one_role_reading_every_dataset(tmp_path):
    pack_dir = tmp_path / "shop"

    summary = write_pack_files(pack_dir, pack="shop", display_name="Shop", source="shop",
                               tables=[WIDGETS, SALES, REFUNDS], views=VIEWS, profile=PROFILE)

    pack = load_pack(pack_dir, schema_dir=SCHEMA_DIR)
    assert pack.business_profile.conventions == [] and pack.business_profile.currency == "USD"
    [role] = pack.policies.roles
    assert role.id == READER_ROLE and role.status == "approved"
    assert {grant.dataset for grant in role.datasets} == {"shop__sales__wide", "shop__widgets", "shop__sales"}
    assert [(item.from_dataset, item.status) for item in pack.relationships.relationships] == [("shop__sales", "approved")]
    assert not (pack_dir / "eval.yaml").exists()
    assert summary == {"datasets": 3, "relationships": 1, "skipped": ["shop__refunds"]}


def test_writing_again_replaces_the_files(tmp_path):
    pack_dir = tmp_path / "shop"
    pack_dir.mkdir()
    (pack_dir / "metrics.yaml").write_text("metrics: [{id: old}]\n", encoding="utf-8")

    write_pack_files(pack_dir, pack="shop", display_name="Shop", source="shop", tables=[WIDGETS], views=VIEWS[:1],
                     profile=PROFILE)

    assert yaml.safe_load((pack_dir / "metrics.yaml").read_text(encoding="utf-8")) == {"metrics": []}
