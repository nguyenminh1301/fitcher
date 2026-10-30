import textwrap

import pytest

from jobs.lib.manifest import ManifestError, load_manifest

VALID = """
name: shop
hf_repo: example/shop
revision: abc123
dbt_tag: shop
tables:
  - name: orders
    file: orders.parquet
    format: parquet
    expected_rows: 10
  - name: items
    file: items.parquet
    format: parquet
    expected_rows: 30
"""


def write(directory, name, text):
    (directory / f"{name}.yaml").write_text(textwrap.dedent(text))


def with_table(table_yaml):
    return f"""
name: shop
hf_repo: example/shop
revision: abc123
dbt_tag: shop
tables:
{textwrap.indent(textwrap.dedent(table_yaml).strip(), "  ")}
"""


def assert_rejected(tmp_path, text, match):
    write(tmp_path, "shop", text)
    with pytest.raises(ManifestError, match=match):
        load_manifest("shop", tmp_path)


def test_loads_valid_manifest(tmp_path):
    write(tmp_path, "shop", VALID)
    manifest = load_manifest("shop", tmp_path)
    assert manifest.name == "shop"
    assert manifest.revision == "abc123"
    assert [t.name for t in manifest.tables] == ["orders", "items"]
    assert manifest.tables[0].expected_rows == 10
    assert manifest.tables[0].date_range is None


def test_missing_tables_rejected(tmp_path):
    assert_rejected(tmp_path, VALID.split("tables:")[0], "tables")


def test_empty_tables_rejected(tmp_path):
    assert_rejected(tmp_path, VALID.split("tables:")[0] + "tables: []\n", "tables")


@pytest.mark.parametrize("value", ['"10"', "-1", "true", "1.5"])
def test_bad_row_count_type_rejected(tmp_path, value):
    table = f"""
    - name: orders
      file: orders.parquet
      format: parquet
      expected_rows: {value}
    """
    assert_rejected(tmp_path, with_table(table), "expected_rows")


def test_duplicate_table_names_rejected(tmp_path):
    table = """
    - {name: orders, file: a.parquet, format: parquet, expected_rows: 1}
    - {name: orders, file: b.parquet, format: parquet, expected_rows: 1}
    """
    assert_rejected(tmp_path, with_table(table), "orders")


def test_unsupported_format_rejected(tmp_path):
    table = "- {name: orders, file: orders.csv, format: csv, expected_rows: 1}"
    assert_rejected(tmp_path, with_table(table), "format")


def test_unknown_table_key_rejected(tmp_path):
    table = "- {name: orders, file: a.parquet, format: parquet, expected_rows: 1, rows: 2}"
    assert_rejected(tmp_path, with_table(table), "rows")


DATE_RANGE = "date_range: {column: order_date, start: '2024-01-01', end: '2025-01-01'}"


def test_date_range_requires_card_rows(tmp_path):
    table = f"- {{name: orders, file: a.parquet, format: parquet, expected_rows: 10, {DATE_RANGE}}}"
    assert_rejected(tmp_path, with_table(table), "card_rows")


def test_date_range_with_card_rows_loads(tmp_path):
    table = f"- {{name: orders, file: a.parquet, format: parquet, expected_rows: 10, card_rows: 20, {DATE_RANGE}}}"
    write(tmp_path, "shop", with_table(table))
    spec = load_manifest("shop", tmp_path).tables[0]
    assert spec.card_rows == 20
    assert spec.date_range.column == "order_date"
    assert (spec.date_range.start, spec.date_range.end) == ("2024-01-01", "2025-01-01")


def test_card_rows_below_expected_rows_rejected(tmp_path):
    table = f"- {{name: orders, file: a.parquet, format: parquet, expected_rows: 10, card_rows: 5, {DATE_RANGE}}}"
    assert_rejected(tmp_path, with_table(table), "card_rows")


def test_card_rows_without_date_range_rejected(tmp_path):
    table = "- {name: orders, file: a.parquet, format: parquet, expected_rows: 10, card_rows: 20}"
    assert_rejected(tmp_path, with_table(table), "card_rows")


def test_date_range_must_be_ordered(tmp_path):
    date_range = "date_range: {column: order_date, start: '2025-01-01', end: '2025-01-01'}"
    table = f"- {{name: orders, file: a.parquet, format: parquet, expected_rows: 10, card_rows: 20, {date_range}}}"
    assert_rejected(tmp_path, with_table(table), "date_range")


def test_name_must_match_file(tmp_path):
    write(tmp_path, "shop", VALID.replace("name: shop", "name: other"))
    with pytest.raises(ManifestError, match="other"):
        load_manifest("shop", tmp_path)


def test_duplicate_dbt_tag_across_manifests_rejected(tmp_path):
    write(tmp_path, "shop", VALID)
    write(tmp_path, "store", VALID.replace("name: shop", "name: store"))
    with pytest.raises(ManifestError, match="store.yaml"):
        load_manifest("shop", tmp_path)


def test_unknown_source_rejected(tmp_path):
    with pytest.raises(ManifestError, match="missing"):
        load_manifest("missing", tmp_path)


@pytest.mark.parametrize(
    ("old", "new"),
    [("name: orders", "name: 'orders; drop'"), ("dbt_tag: shop", "dbt_tag: 'my shop'")],
)
def test_unsafe_identifiers_rejected(tmp_path, old, new):
    assert_rejected(tmp_path, VALID.replace(old, new), "identifier")


def test_repository_manifest_is_valid():
    manifest = load_manifest("ecommerce_twin")
    assert manifest.hf_repo == "ziadatalabs/FreeEcommerceTwin14M"
    assert manifest.revision == "d1bddd9a97a4fe31fd193e48c5826bbcd2b3022f"
    assert manifest.dbt_tag == "ecommerce_twin"
    assert {t.name: t.expected_rows for t in manifest.tables} == {
        "customers": 1_000_000,
        "products": 50_000,
        "sessions": 7_455_296,
        "orders": 1_075_683,
        "order_items": 4_280_732,
        "returns": 400_293,
        "support_tickets": 66_938,
    }
