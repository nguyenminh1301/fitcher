"""Cross-reference validation between pack files and against the warehouse catalog."""

from conftest import SCHEMA_DIR, FakeCatalog, fixture_catalog
import pytest

from app.packs.loader import PackValidationError, load_pack


def _set(path, value):
    def change(data):
        for key in path[:-1]:
            data = data[key]
        data[path[-1]] = value
    return change


def _append(path, value):
    def change(data):
        for key in path:
            data = data[key]
        data.append(value)
    return change


def _copy_first(key):
    def change(data):
        data[key].append(dict(data[key][0]))
    return change


# (file, change, file named in the message, item path, expected message text)
BROKEN_REFERENCES = [
    ("business_profile.yaml", _set(("name",), "other"), "business_profile.yaml", "name", "must equal the pack directory name 'minimal'"),
    ("business_profile.yaml", _set(("conventions", 0, "metric"), "nope"), "business_profile.yaml", "conventions[0].metric", "unknown metric 'nope'"),
    ("datasets.yaml", _copy_first("datasets"), "datasets.yaml", "datasets[2].id", "duplicate id 'widget_sales'"),
    ("datasets.yaml", _set(("datasets", 0, "time_column"), "widget_name"), "datasets.yaml", "datasets[0].time_column", "must name a column with role time"),
    ("datasets.yaml", _set(("datasets", 0, "columns", 3, "indexable"), True), "datasets.yaml", "datasets[0].columns[3].indexable", "only string columns can be indexable"),
    ("datasets.yaml", _append(("datasets", 0, "columns"), {"name": "sold_on", "type": "date", "role": "time", "description": "Again."}), "datasets.yaml", "datasets[0].columns[4].name", "duplicate column 'sold_on'"),
    ("datasets.yaml", _set(("datasets", 1, "allowed_roles"), []), "datasets.yaml", "datasets[1].allowed_roles", "must equal the roles granted this dataset in policies.yaml: ['viewer']"),
    ("glossary.yaml", _set(("terms", 0, "targets", 0, "metric"), "nope"), "glossary.yaml", "terms[0].targets[0].metric", "unknown metric 'nope'"),
    ("glossary.yaml", _set(("terms", 1, "targets", 0, "dataset"), "nope"), "glossary.yaml", "terms[1].targets[0].dataset", "unknown dataset 'nope'"),
    ("glossary.yaml", _set(("terms", 1, "targets", 0, "column"), "nope"), "glossary.yaml", "terms[1].targets[0].column", "unknown column 'nope' in dataset 'widget_sales'"),
    ("metrics.yaml", _set(("metrics", 1, "dataset"), "nope"), "metrics.yaml", "metrics[1].dataset", "unknown dataset 'nope'"),
    ("metrics.yaml", _copy_first("metrics"), "metrics.yaml", "metrics[2].id", "duplicate id 'widget_revenue'"),
    ("relationships.yaml", _set(("relationships", 0, "to_dataset"), "nope"), "relationships.yaml", "relationships[0].to_dataset", "unknown dataset 'nope'"),
    ("relationships.yaml", _set(("relationships", 0, "on", 0, "from_column"), "nope"), "relationships.yaml", "relationships[0].on[0].from_column", "unknown column 'nope' in dataset 'widget_refunds'"),
    ("relationships.yaml", _set(("relationships", 0, "on", 0, "to_column"), "refund_total"), "relationships.yaml", "relationships[0].on[0].to_column", "unknown column 'refund_total' in dataset 'widget_sales'"),
    ("examples.yaml", _set(("examples", 0, "metrics"), ["nope"]), "examples.yaml", "examples[0].metrics[0]", "unknown metric 'nope'"),
    ("examples.yaml", _set(("examples", 0, "datasets"), ["nope"]), "examples.yaml", "examples[0].datasets[0]", "unknown dataset 'nope'"),
    ("policies.yaml", _set(("roles", 0, "datasets", 0, "columns", 1), "nope"), "policies.yaml", "roles[0].datasets[0].columns[1]", "unknown column 'nope' in dataset 'widget_sales'"),
    ("policies.yaml", _set(("roles", 0, "datasets", 1, "dataset"), "nope"), "policies.yaml", "roles[0].datasets[1].dataset", "unknown dataset 'nope'"),
    ("eval.yaml", _set(("cases", 0, "role"), "nope"), "eval.yaml", "cases[0].role", "unknown role 'nope'"),
    ("eval.yaml", _set(("cases", 0, "expected", "metrics"), ["nope"]), "eval.yaml", "cases[0].expected.metrics[0]", "unknown metric 'nope'"),
    ("eval.yaml", _set(("cases", 0, "expected", "rank_by"), "nope"), "eval.yaml", "cases[0].expected.rank_by", "unknown metric 'nope'"),
    ("eval.yaml", _set(("cases", 0, "expected", "dataset"), "nope"), "eval.yaml", "cases[0].expected.dataset", "unknown dataset 'nope'"),
    ("eval.yaml", _set(("cases", 0, "expected", "columns"), ["refund_total"]), "eval.yaml", "cases[0].expected.columns[0]", "unknown column 'refund_total' in dataset 'widget_sales'"),
]


@pytest.mark.parametrize(
    ("file_name", "change", "reported_file", "item_path", "message"),
    BROKEN_REFERENCES,
    ids=[f"{case[2]}:{case[3]}" for case in BROKEN_REFERENCES],
)
def test_broken_reference_is_rejected(pack_dir, edit_pack, file_name, change, reported_file, item_path, message):
    edit_pack(file_name, change)

    with pytest.raises(PackValidationError) as error:
        load_pack(pack_dir, schema_dir=SCHEMA_DIR)

    assert f"{reported_file}: {item_path}: {message}" in [str(issue) for issue in error.value.issues]


def test_pack_matching_the_catalog_loads(pack_dir):
    pack = load_pack(pack_dir, schema_dir=SCHEMA_DIR, catalog=fixture_catalog())

    assert [item.id for item in pack.datasets.datasets] == ["widget_sales", "widget_refunds"]


def test_missing_table_is_rejected(pack_dir):
    catalog = fixture_catalog()
    del catalog.tables["widget_refunds"]

    with pytest.raises(PackValidationError) as error:
        load_pack(pack_dir, schema_dir=SCHEMA_DIR, catalog=catalog)

    assert [str(issue) for issue in error.value.issues] == [
        "datasets.yaml: datasets[1].id: table 'widget_refunds' not found in the warehouse"
    ]


def test_missing_column_is_rejected(pack_dir):
    catalog = FakeCatalog({**fixture_catalog().tables, "widget_sales": {"sale_ref", "sold_on", "sale_amount"}})

    with pytest.raises(PackValidationError) as error:
        load_pack(pack_dir, schema_dir=SCHEMA_DIR, catalog=catalog)

    assert [str(issue) for issue in error.value.issues] == [
        "datasets.yaml: datasets[0].columns[2].name: column 'widget_name' not found in table 'widget_sales'"
    ]


def test_schema_errors_are_reported_before_references(pack_dir, edit_pack):
    edit_pack("metrics.yaml", _set(("metrics", 0, "unit"), "furlongs"))
    edit_pack("metrics.yaml", _set(("metrics", 1, "dataset"), "nope"))

    with pytest.raises(PackValidationError) as error:
        load_pack(pack_dir, schema_dir=SCHEMA_DIR)

    assert [issue.path for issue in error.value.issues] == ["metrics[0].unit"]
