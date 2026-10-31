"""JSON Schema validation of the eight Domain Pack files."""

from pathlib import Path

from conftest import SCHEMA_DIR
import pytest

from app.packs.loader import PackValidationError, load_pack


def _at(data, path):
    for key in path[:-1]:
        data = data[key]
    return data, path[-1]


def _delete(path):
    def change(data):
        parent, key = _at(data, path)
        del parent[key]
    return change


def _set(path, value):
    def change(data):
        parent, key = _at(data, path)
        parent[key] = value
    return change


# (file, change, item path in the message, expected message text)
INVALID_FILES = [
    ("business_profile.yaml", _delete(("currency",)), "currency", "required field is missing"),
    ("business_profile.yaml", _set(("colour",), "red"), "colour", "unknown field"),
    # The user's time zone and answer language come from each request, never from the pack.
    ("business_profile.yaml", _set(("timezone",), "UTC"), "timezone", "unknown field"),
    ("business_profile.yaml", _set(("language",), "en"), "language", "unknown field"),
    ("business_profile.yaml", _set(("conventions", 0, "status"), "pending"), "conventions[0].status", "is not one of"),
    ("datasets.yaml", _delete(("datasets", 0, "grain")), "datasets[0].grain", "required field is missing"),
    ("datasets.yaml", _set(("datasets", 0, "columns", 0, "colour"), "red"), "datasets[0].columns[0].colour", "unknown field"),
    ("datasets.yaml", _set(("datasets", 0, "columns", 0, "role"), "metric"), "datasets[0].columns[0].role", "is not one of"),
    ("glossary.yaml", _delete(("terms", 0, "definition")), "terms[0].definition", "required field is missing"),
    ("glossary.yaml", _set(("terms", 0, "aliases", "fr"), ["recette"]), "terms[0].aliases.fr", "unknown field"),
    ("glossary.yaml", _set(("terms", 0, "targets", 0, "kind"), "table"), "terms[0].targets[0].kind", "is not one of"),
    ("metrics.yaml", _delete(("metrics", 0, "sql_expr")), "metrics[0].sql_expr", "required field is missing"),
    ("metrics.yaml", _set(("metrics", 0, "colour"), "red"), "metrics[0].colour", "unknown field"),
    ("metrics.yaml", _set(("metrics", 0, "unit"), "furlongs"), "metrics[0].unit", "is not one of"),
    ("relationships.yaml", _delete(("relationships", 0, "cardinality")), "relationships[0].cardinality", "required field is missing"),
    ("relationships.yaml", _set(("relationships", 0, "on", 0, "colour"), "red"), "relationships[0].on[0].colour", "unknown field"),
    ("relationships.yaml", _set(("relationships", 0, "cardinality"), "many_to_many"), "relationships[0].cardinality", "is not one of"),
    ("examples.yaml", _delete(("examples", 0, "sql")), "examples[0].sql", "required field is missing"),
    ("examples.yaml", _set(("examples", 0, "colour"), "red"), "examples[0].colour", "unknown field"),
    ("examples.yaml", _set(("examples", 0, "evidence", 0, "kind"), "rumour"), "examples[0].evidence[0].kind", "is not one of"),
    ("policies.yaml", _delete(("roles", 0, "datasets", 0, "columns")), "roles[0].datasets[0].columns", "required field is missing"),
    ("policies.yaml", _set(("roles", 0, "colour"), "red"), "roles[0].colour", "unknown field"),
    ("policies.yaml", _set(("roles", 0, "status"), "maybe"), "roles[0].status", "is not one of"),
    ("eval.yaml", _delete(("cases", 0, "expected", "intent")), "cases[0].expected.intent", "required field is missing"),
    ("eval.yaml", _set(("cases", 0, "expected", "colour"), "red"), "cases[0].expected.colour", "unknown field"),
    ("eval.yaml", _set(("cases", 0, "category"), "trivia"), "cases[0].category", "is not one of"),
]


def test_minimal_pack_loads(pack_dir: Path):
    pack = load_pack(pack_dir, schema_dir=SCHEMA_DIR)

    assert pack.name == "minimal"
    assert [item.id for item in pack.metrics.metrics] == ["widget_revenue", "refunded_value"]
    assert pack.datasets.datasets[0].columns[2].indexable is True


@pytest.mark.parametrize(
    ("file_name", "change", "item_path", "message"),
    INVALID_FILES,
    ids=[f"{case[0]}:{case[2]}:{case[3]}" for case in INVALID_FILES],
)
def test_schema_rejects_invalid_item(pack_dir, edit_pack, file_name, change, item_path, message):
    edit_pack(file_name, change)

    with pytest.raises(PackValidationError) as error:
        load_pack(pack_dir, schema_dir=SCHEMA_DIR)

    prefix = f"{file_name}: {item_path}: "
    lines = [line.strip() for line in str(error.value).splitlines() if line.strip().startswith(prefix)]
    assert len(lines) == 1
    assert message in lines[0]


def test_yes_and_on_are_not_booleans(pack_dir, edit_pack):
    edit_pack("glossary.yaml", _set(("terms", 0, "aliases", "en"), ["yes", "on", "no"]))
    text = (pack_dir / "glossary.yaml").read_text(encoding="utf-8").replace("'", "")
    (pack_dir / "glossary.yaml").write_text(text, encoding="utf-8")

    pack = load_pack(pack_dir, schema_dir=SCHEMA_DIR)

    assert pack.glossary.terms[0].aliases.en == ["yes", "on", "no"]


def test_missing_file_is_reported(pack_dir: Path):
    (pack_dir / "eval.yaml").unlink()

    with pytest.raises(PackValidationError, match="eval.yaml: file is missing"):
        load_pack(pack_dir, schema_dir=SCHEMA_DIR)


def test_invalid_yaml_is_reported(pack_dir: Path):
    (pack_dir / "metrics.yaml").write_text("metrics: [unclosed\n", encoding="utf-8")

    with pytest.raises(PackValidationError, match="metrics.yaml: invalid YAML"):
        load_pack(pack_dir, schema_dir=SCHEMA_DIR)


def test_dates_stay_strings(pack_dir, edit_pack):
    edit_pack("eval.yaml", _set(("cases", 0, "expected", "periods"), [{"label": "Q1", "start": "2024-01-01", "end": "2024-04-01"}]))
    text = (pack_dir / "eval.yaml").read_text(encoding="utf-8").replace("'2024-01-01'", "2024-01-01")
    (pack_dir / "eval.yaml").write_text(text, encoding="utf-8")

    pack = load_pack(pack_dir, schema_dir=SCHEMA_DIR)

    assert pack.eval.cases[0].expected.periods[0].start == "2024-01-01"


def test_every_problem_is_reported_at_once(pack_dir, edit_pack):
    edit_pack("metrics.yaml", _set(("metrics", 0, "unit"), "furlongs"))
    edit_pack("glossary.yaml", _delete(("terms", 1, "term")))

    with pytest.raises(PackValidationError) as error:
        load_pack(pack_dir, schema_dir=SCHEMA_DIR)

    assert {(issue.file, issue.path) for issue in error.value.issues} == {
        ("metrics.yaml", "metrics[0].unit"),
        ("glossary.yaml", "terms[1].term"),
    }
