import textwrap

import pytest

from jobs.lib.source_manifest import SOURCES_DIR, ManifestError, load_manifest

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
    assert (manifest.kind, manifest.mode, manifest.connection_env) == ("huggingface", "copy", None)


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


def test_shared_dbt_tag_with_other_tables_rejected(tmp_path):
    write(tmp_path, "shop", VALID)
    write(tmp_path, "store", VALID.replace("name: shop", "name: store").replace("name: items", "name: lines"))
    with pytest.raises(ManifestError, match="store.yaml"):
        load_manifest("shop", tmp_path)


def test_shared_dbt_tag_with_the_same_tables_loads(tmp_path):
    # Alternative sources feed one set of dbt models, one source at a time.
    write(tmp_path, "shop", VALID)
    write(tmp_path, "store", POSTGRES.replace("name: pg_shop", "name: store"))
    assert load_manifest("shop", tmp_path).dbt_tag == load_manifest("store", tmp_path).dbt_tag


def test_unknown_source_rejected(tmp_path):
    with pytest.raises(ManifestError, match="missing"):
        load_manifest("missing", tmp_path)


@pytest.mark.parametrize(
    ("old", "new"),
    [("name: orders", "name: 'orders; drop'"), ("dbt_tag: shop", "dbt_tag: 'my shop'")],
)
def test_unsafe_identifiers_rejected(tmp_path, old, new):
    assert_rejected(tmp_path, VALID.replace(old, new), "identifier")


NL = "\n"

POSTGRES = """
name: pg_shop
kind: postgres
connection_env: PG_SHOP
dbt_tag: shop
tables:
  - {name: orders, expected_rows: 10}
  - {name: items, source: order_items}
"""

MONGODB = """
name: doc_shop
kind: mongodb
mode: live
connection_env: DOC_SHOP
dbt_tag: doc_shop
tables:
  - name: orders
    source: shop_orders
    columns:
      - {name: order_id, type: String}
      - {name: quantity, type: Int32}
      - {name: amount, type: "Decimal(12, 2)"}
      - {name: placed_at, type: "Nullable(DateTime64(3, 'UTC'))"}
"""

FILES = """
name: file_shop
kind: files
mode: live
connection_env: FILE_SHOP
dbt_tag: file_shop
tables:
  - {name: orders, path: exports/orders.csv, format: csv, expected_rows: 5}
  - {name: items, path: exports/items.parquet, format: parquet}
"""


def load_text(tmp_path, name, text):
    write(tmp_path, name, text)
    return load_manifest(name, tmp_path)


def test_postgres_manifest_defaults_to_copy_and_table_names(tmp_path):
    manifest = load_text(tmp_path, "pg_shop", POSTGRES)
    assert (manifest.kind, manifest.mode, manifest.connection_env) == ("postgres", "copy", "PG_SHOP")
    assert manifest.hf_repo is None and manifest.revision is None
    assert [(t.name, t.source_name, t.expected_rows) for t in manifest.tables] == [
        ("orders", "orders", 10),
        ("items", "order_items", None),
    ]


def test_mongodb_manifest_lists_typed_columns(tmp_path):
    manifest = load_text(tmp_path, "doc_shop", MONGODB)
    table = manifest.tables[0]
    assert (manifest.mode, table.source_name) == ("live", "shop_orders")
    assert [(c.name, c.type) for c in table.columns] == [
        ("order_id", "String"),
        ("quantity", "Int32"),
        ("amount", "Decimal(12, 2)"),
        ("placed_at", "Nullable(DateTime64(3, 'UTC'))"),
    ]


def test_files_manifest_lists_paths_and_formats(tmp_path):
    manifest = load_text(tmp_path, "file_shop", FILES)
    assert [(t.source_name, t.format) for t in manifest.tables] == [
        ("exports/orders.csv", "csv"),
        ("exports/items.parquet", "parquet"),
    ]


@pytest.mark.parametrize(
    ("text", "old", "new", "match"),
    [
        (POSTGRES, "kind: postgres", "kind: oracle", "kind"),
        (POSTGRES, "connection_env: PG_SHOP", "connection_env: PG_SHOP" + NL + "mode: stream", "mode"),
        (POSTGRES, "connection_env: PG_SHOP" + NL, "", "connection_env"),
        (POSTGRES, "connection_env: PG_SHOP", "connection_env: pg-shop", "connection_env"),
        (POSTGRES, "connection_env: PG_SHOP", "connection_env: PG_SHOP" + NL + "hf_repo: example/shop", "hf_repo"),
        (POSTGRES, "{name: orders, expected_rows: 10}", "{name: orders, file: a.parquet}", "file"),
        (POSTGRES, "source: order_items", "source: 'items; drop'", "source"),
        (MONGODB, "    columns:" + NL, "    fields:" + NL, "columns|fields"),
        (MONGODB, "type: Int32", "type: 'Int32) ENGINE = Memory --'", "type"),
        (MONGODB, "{name: order_id, type: String}", "{name: order_id, type: Array(String)}", "type"),
        (FILES, "format: csv", "format: json", "format"),
        (FILES, "path: exports/orders.csv", "path: ../orders.csv", "path"),
        (FILES, "path: exports/orders.csv", "path: \"orders'.csv\"", "path"),
    ],
)
def test_invalid_source_fields_rejected(tmp_path, text, old, new, match):
    assert old in text
    name = text.split("name: ", 1)[1].split(NL, 1)[0]
    assert_rejected_as(tmp_path, name, text.replace(old, new), match)


def test_huggingface_source_cannot_be_live(tmp_path):
    assert_rejected(tmp_path, VALID.replace("dbt_tag: shop", "dbt_tag: shop" + NL + "mode: live"), "live|mode")


def test_huggingface_source_needs_its_revision(tmp_path):
    assert_rejected(tmp_path, VALID.replace("revision: abc123" + NL, ""), "revision")


def test_huggingface_source_needs_row_counts(tmp_path):
    table = "- {name: orders, file: a.parquet, format: parquet}"
    assert_rejected(tmp_path, with_table(table), "expected_rows")


def assert_rejected_as(tmp_path, name, text, match):
    write(tmp_path, name, text)
    with pytest.raises(ManifestError, match=match):
        load_manifest(name, tmp_path)


def test_every_repository_manifest_is_valid():
    names = [path.stem for path in SOURCES_DIR.glob("*.yaml")]
    assert "ecommerce_twin" in names
    for name in names:
        assert load_manifest(name).name == name


def test_repository_manifest_is_valid():
    manifest = load_manifest("ecommerce_twin")
    assert manifest.hf_repo == "ziadatalabs/FreeEcommerceTwin14M"
    assert manifest.revision == "d1bddd9a97a4fe31fd193e48c5826bbcd2b3022f"
    assert manifest.dbt_tag == "ecommerce_twin"
    assert (manifest.kind, manifest.mode) == ("huggingface", "copy")
    assert {t.name: t.expected_rows for t in manifest.tables} == {
        "customers": 1_000_000,
        "products": 50_000,
        "sessions": 7_455_296,
        "orders": 1_075_683,
        "order_items": 4_280_732,
        "returns": 400_293,
        "support_tickets": 66_938,
    }
