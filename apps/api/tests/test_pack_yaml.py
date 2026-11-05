from pathlib import Path
import shutil

import pytest

from app.onboarding.pack_yaml import ITEM_LISTS, ItemNotFound, PackFiles
from app.packs.loader import PACK_FILES, PackValidationError

ROOT = Path(__file__).resolve().parents[3]
PACK = ROOT / "packs" / "ecommerce_twin"
SCHEMA_DIR = ROOT / "packs" / "_schema"


@pytest.fixture
def pack_dir(tmp_path: Path) -> Path:
    target = tmp_path / "ecommerce_twin"
    shutil.copytree(PACK, target, ignore=shutil.ignore_patterns("sample_data", "__pycache__"))
    return target


def draft_metric(**overrides) -> dict:
    return {
        "id": "gross_margin", "name": "Gross margin", "description": "Net sales minus product cost.",
        "dataset": "sales_lines", "sql_expr": "sum(line_amount)", "grain": "day", "unit": "currency",
        "owner": "sales analytics", "status": "draft", "evidence": [{"kind": "profile", "ref": "sales_lines"}],
        "confidence": 0.6, **overrides,
    }


def test_every_pack_file_has_an_item_list():
    assert set(ITEM_LISTS) == set(PACK_FILES)


@pytest.mark.parametrize("file", sorted(PACK_FILES))
def test_saving_an_unchanged_file_keeps_it_byte_for_byte(pack_dir, file):
    before = (pack_dir / file).read_bytes()
    PackFiles(pack_dir, SCHEMA_DIR).save(file)
    assert (pack_dir / file).read_bytes() == before


def test_a_draft_never_overwrites_an_approved_item(pack_dir):
    before = (pack_dir / "metrics.yaml").read_bytes()
    files = PackFiles(pack_dir, SCHEMA_DIR)

    result = files.merge_drafts("metrics.yaml", [draft_metric(id="net_sales", description="Replaced.")])
    files.save("metrics.yaml")

    assert (result.added, result.updated, result.skipped_approved) == ([], [], ["net_sales"])
    assert (pack_dir / "metrics.yaml").read_bytes() == before


def test_new_drafts_are_appended_and_existing_drafts_updated(pack_dir):
    files = PackFiles(pack_dir, SCHEMA_DIR)
    assert files.merge_drafts("metrics.yaml", [draft_metric()]).added == ["gross_margin"]
    files.save("metrics.yaml")

    files = PackFiles(pack_dir, SCHEMA_DIR)
    result = files.merge_drafts("metrics.yaml", [draft_metric(description="Better.", confidence=0.8)])
    files.save("metrics.yaml")

    assert result.updated == ["gross_margin"]
    text = (pack_dir / "metrics.yaml").read_text(encoding="utf-8")
    assert text.index("id: net_sales") < text.index("id: gross_margin")
    item = PackFiles(pack_dir, SCHEMA_DIR).find("metrics.yaml", "gross_margin")
    assert item["description"] == "Better." and item["confidence"] == 0.8 and item["status"] == "draft"


def test_an_edit_keeps_comments_and_anchors_and_returns_the_item_to_draft(pack_dir):
    files = PackFiles(pack_dir, SCHEMA_DIR)
    files.update("glossary.yaml", "best_selling", {"definition": "Ranked by net sales."})
    files.save("glossary.yaml")

    text = (pack_dir / "glossary.yaml").read_text(encoding="utf-8")
    assert text.startswith("# Vietnamese aliases are drafted for owner review.\n")
    assert "evidence: &owner [{kind: manual, ref: docs/plans/phase-02-domain-pack-and-compiler.md}]" in text
    item = PackFiles(pack_dir, SCHEMA_DIR).find("glossary.yaml", "best_selling")
    assert item["definition"] == "Ranked by net sales." and item["status"] == "draft"
    assert "\r\n" not in (pack_dir / "glossary.yaml").read_bytes().decode()


def test_approve_and_delete(pack_dir):
    files = PackFiles(pack_dir, SCHEMA_DIR)
    files.merge_drafts("metrics.yaml", [draft_metric()])
    files.approve("metrics.yaml", "gross_margin")
    assert files.find("metrics.yaml", "gross_margin")["status"] == "approved"
    files.delete("metrics.yaml", "gross_margin")
    with pytest.raises(ItemNotFound):
        files.find("metrics.yaml", "gross_margin")


def test_business_profile_conventions_are_items(pack_dir):
    files = PackFiles(pack_dir, SCHEMA_DIR)
    ids = [item["id"] for item in files.items("business_profile.yaml")]
    assert ids and files.find("business_profile.yaml", ids[0])["id"] == ids[0]


def test_an_invalid_change_is_refused_and_the_file_is_untouched(pack_dir):
    before = (pack_dir / "metrics.yaml").read_bytes()
    files = PackFiles(pack_dir, SCHEMA_DIR)
    files.update("metrics.yaml", "net_sales", {"grain": "fortnight"})

    with pytest.raises(PackValidationError, match="grain"):
        files.save("metrics.yaml")
    assert (pack_dir / "metrics.yaml").read_bytes() == before
    assert not list(pack_dir.glob("*.tmp"))


@pytest.mark.parametrize("file", sorted(set(PACK_FILES) - {"policies.yaml"}))
def test_a_file_without_hand_wrapped_lists_round_trips_exactly(pack_dir, file):
    # policies.yaml wraps long column lists by hand; a change to it writes each list on one line.
    assert PackFiles(pack_dir, SCHEMA_DIR).text(file) == (pack_dir / file).read_text(encoding="utf-8")
