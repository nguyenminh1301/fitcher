from pathlib import Path
import shutil

from conftest import FIXTURE_PACK, SCHEMA_DIR
import pytest

from app.onboarding.pack_yaml import ITEM_LISTS, ItemNotFound, PackFiles
from app.packs.loader import PACK_FILES, PackValidationError

COMMENT = "# Aliases are drafted for owner review.\n"
WRAPPED = """      - dataset: widget_sales
        columns: [sale_ref, sold_on,
          widget_name, sale_amount]
"""


@pytest.fixture
def pack_dir(tmp_path: Path) -> Path:
    """The fixture pack plus what people write by hand: a comment, an anchor with its alias, a wrapped list."""
    target = tmp_path / "minimal"
    shutil.copytree(FIXTURE_PACK, target)
    glossary = (target / "glossary.yaml").read_text(encoding="utf-8")
    glossary = glossary.replace("evidence: [{kind: manual, ref: fixture}]", "evidence: &owner [{kind: manual, ref: fixture}]", 1)
    glossary = glossary.replace("evidence: [{kind: manual, ref: fixture}]", "evidence: *owner")
    (target / "glossary.yaml").write_bytes((COMMENT + glossary).encode())
    policies = (target / "policies.yaml").read_text(encoding="utf-8")
    policies = policies.replace(
        "      - dataset: widget_sales\n        columns: [sale_ref, sold_on, widget_name, sale_amount]\n", WRAPPED,
    )
    assert WRAPPED in policies
    (target / "policies.yaml").write_bytes(policies.encode())
    return target


def draft_metric(**overrides) -> dict:
    return {
        "id": "widget_margin", "name": "Widget margin", "description": "Revenue minus cost.",
        "dataset": "widget_sales", "sql_expr": "sum(sale_amount)", "grain": "day", "unit": "currency",
        "owner": "finance", "status": "draft", "evidence": [{"kind": "profile", "ref": "widget_sales"}],
        "confidence": 0.6, **overrides,
    }


def test_every_pack_file_has_an_item_list():
    assert set(ITEM_LISTS) == set(PACK_FILES)


@pytest.mark.parametrize("file", sorted(PACK_FILES))
def test_saving_an_unchanged_file_keeps_it_byte_for_byte(pack_dir, file):
    before = (pack_dir / file).read_bytes()
    PackFiles(pack_dir, SCHEMA_DIR).save(file)
    assert (pack_dir / file).read_bytes() == before


@pytest.mark.parametrize("file", sorted(set(PACK_FILES) - {"policies.yaml"}))
def test_a_file_without_hand_wrapped_lists_round_trips_exactly(pack_dir, file):
    # A wrapped flow list cannot be reproduced; a change to such a file writes the list on one line.
    assert PackFiles(pack_dir, SCHEMA_DIR).text(file) == (pack_dir / file).read_text(encoding="utf-8")


def test_a_draft_never_overwrites_an_approved_item(pack_dir):
    before = (pack_dir / "metrics.yaml").read_bytes()
    files = PackFiles(pack_dir, SCHEMA_DIR)

    result = files.merge_drafts("metrics.yaml", [draft_metric(id="widget_revenue", description="Replaced.")])
    files.save("metrics.yaml")

    assert (result.added, result.updated, result.skipped_approved) == ([], [], ["widget_revenue"])
    assert (pack_dir / "metrics.yaml").read_bytes() == before


def test_new_drafts_are_appended_and_existing_drafts_updated(pack_dir):
    files = PackFiles(pack_dir, SCHEMA_DIR)
    assert files.merge_drafts("metrics.yaml", [draft_metric()]).added == ["widget_margin"]
    files.save("metrics.yaml")

    files = PackFiles(pack_dir, SCHEMA_DIR)
    result = files.merge_drafts("metrics.yaml", [draft_metric(description="Better.", confidence=0.8)])
    files.save("metrics.yaml")

    assert result.updated == ["widget_margin"]
    text = (pack_dir / "metrics.yaml").read_text(encoding="utf-8")
    assert text.index("id: widget_revenue") < text.index("id: widget_margin")
    item = PackFiles(pack_dir, SCHEMA_DIR).find("metrics.yaml", "widget_margin")
    assert item["description"] == "Better." and item["confidence"] == 0.8 and item["status"] == "draft"


def test_an_edit_keeps_comments_and_anchors_and_returns_the_item_to_draft(pack_dir):
    files = PackFiles(pack_dir, SCHEMA_DIR)
    term = files.items("glossary.yaml")[-1]["id"]
    files.update("glossary.yaml", term, {"definition": "Edited by a reviewer."})
    files.save("glossary.yaml")

    raw = (pack_dir / "glossary.yaml").read_bytes().decode()
    assert raw.startswith(COMMENT) and "\r\n" not in raw
    assert "evidence: &owner [{kind: manual, ref: fixture}]" in raw and "evidence: *owner" in raw
    item = PackFiles(pack_dir, SCHEMA_DIR).find("glossary.yaml", term)
    assert item["definition"] == "Edited by a reviewer." and item["status"] == "draft"


def test_a_changed_file_with_a_wrapped_list_keeps_its_values(pack_dir):
    files = PackFiles(pack_dir, SCHEMA_DIR)
    files.update("policies.yaml", "viewer", {"description": "Reads every fixture dataset again."})
    files.save("policies.yaml")
    columns = PackFiles(pack_dir, SCHEMA_DIR).find("policies.yaml", "viewer")["datasets"][0]["columns"]
    assert list(columns) == ["sale_ref", "sold_on", "widget_name", "sale_amount"]


def test_approve_and_delete(pack_dir):
    files = PackFiles(pack_dir, SCHEMA_DIR)
    files.merge_drafts("metrics.yaml", [draft_metric()])
    files.approve("metrics.yaml", "widget_margin")
    assert files.find("metrics.yaml", "widget_margin")["status"] == "approved"
    files.delete("metrics.yaml", "widget_margin")
    with pytest.raises(ItemNotFound):
        files.find("metrics.yaml", "widget_margin")


def test_business_profile_conventions_are_items(pack_dir):
    files = PackFiles(pack_dir, SCHEMA_DIR)
    ids = [item["id"] for item in files.items("business_profile.yaml")]
    assert ids and files.find("business_profile.yaml", ids[0])["id"] == ids[0]


def test_an_invalid_change_is_refused_and_the_file_is_untouched(pack_dir):
    before = (pack_dir / "metrics.yaml").read_bytes()
    files = PackFiles(pack_dir, SCHEMA_DIR)
    files.update("metrics.yaml", "widget_revenue", {"grain": "fortnight"})

    with pytest.raises(PackValidationError, match="grain"):
        files.save("metrics.yaml")
    assert (pack_dir / "metrics.yaml").read_bytes() == before
    assert not list(pack_dir.glob("*.tmp"))
