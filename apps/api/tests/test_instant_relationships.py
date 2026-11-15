"""Join paths of an instant pack: approved from the source's foreign keys, drafts from the profile (DECISIONS §11)."""

from app.onboarding.marts import MartTable, SourceColumn
from app.onboarding.relationships import candidate_relationships, source_relationships
from app.sources.inspect import ForeignKey


def _table(name: str, keys=(), columns=("widget_id",)) -> MartTable:
    return MartTable(name=name, relation=f"`raw`.`shop__{name}`", live=False,
                     columns=tuple(SourceColumn(column, "Int64") for column in columns), foreign_keys=keys)


WIDGETS = _table("widgets")
SALES = _table("sales", keys=(ForeignKey(("widget_id",), "widgets", ("widget_id",)),), columns=("sale_id", "widget_id"))


def test_a_foreign_key_between_two_selected_tables_becomes_an_approved_join_path():
    found = source_relationships("shop", [WIDGETS, SALES], datasets={"shop__widgets", "shop__sales"})

    assert found == [{
        "id": "shop__sales__widget_id", "description": "Each row of sales references one row of widgets by widget_id.",
        "from_dataset": "shop__sales", "to_dataset": "shop__widgets",
        "on": [{"from_column": "widget_id", "to_column": "widget_id"}], "cardinality": "many_to_one",
        "status": "approved", "evidence": [{"kind": "source", "ref": "foreign key sales(widget_id) -> widgets(widget_id)"}],
        "confidence": 1.0,
    }]


def test_a_foreign_key_to_a_table_without_a_dataset_gives_no_join_path():
    assert source_relationships("shop", [WIDGETS, SALES], datasets={"shop__sales"}) == []


def test_a_composite_foreign_key_joins_on_every_column_pair():
    sales = _table("sales", keys=(ForeignKey(("widget_id", "sale_id"), "widgets", ("widget_id", "batch_id")),),
                   columns=("sale_id", "widget_id"))
    widgets = _table("widgets", columns=("widget_id", "batch_id"))

    [found] = source_relationships("shop", [widgets, sales], datasets={"shop__widgets", "shop__sales"})

    assert found["on"] == [{"from_column": "widget_id", "to_column": "widget_id"},
                           {"from_column": "sale_id", "to_column": "batch_id"}]


def _profile(sales_rows=10, widgets_rows=4, widgets_distinct=4, overlap=1.0):
    return {
        "tables": {
            "shop__sales": {"rows": sales_rows, "columns": {"widget_id": {"type": "number", "distinct": 4}}},
            "shop__widgets": {"rows": widgets_rows, "columns": {"widget_id": {"type": "number", "distinct": widgets_distinct}}},
        },
        "join_candidates": [{"left": "shop__sales.widget_id", "right": "shop__widgets.widget_id", "overlap": overlap}],
    }


def test_a_join_key_candidate_of_the_profile_stays_a_draft():
    [found] = candidate_relationships(_profile(), approved=[])

    assert found["status"] == "draft"
    assert (found["from_dataset"], found["to_dataset"], found["cardinality"]) == ("shop__sales", "shop__widgets", "many_to_one")
    assert found["on"] == [{"from_column": "widget_id", "to_column": "widget_id"}]
    assert found["evidence"] == [{"kind": "profile", "ref": "shop__sales.widget_id"}]
    assert found["confidence"] == 1.0


def test_a_candidate_whose_unique_side_is_the_left_one_is_turned_round():
    profile = _profile(sales_rows=4, widgets_rows=10, widgets_distinct=4)
    profile["tables"]["shop__sales"]["columns"]["widget_id"]["distinct"] = 4

    [found] = candidate_relationships(profile, approved=[])

    assert (found["from_dataset"], found["to_dataset"]) == ("shop__widgets", "shop__sales")


def test_no_candidate_when_neither_side_is_unique_the_overlap_is_low_or_a_key_already_joins():
    assert candidate_relationships(_profile(widgets_rows=8, widgets_distinct=4), approved=[]) == []
    assert candidate_relationships(_profile(overlap=0.5), approved=[]) == []
    approved = source_relationships("shop", [WIDGETS, SALES], datasets={"shop__widgets", "shop__sales"})
    assert candidate_relationships(_profile(), approved=approved) == []
