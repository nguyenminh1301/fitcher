"""Every Domain Pack in packs/ loads, with dataset columns checked against the dbt mart schemas.

The live check against ClickHouse ``system.columns`` runs when a pack is
compiled; this test needs no running service.
"""

from pathlib import Path
import typing

from conftest import FakeCatalog
import pytest
import yaml

from app.packs.loader import load_pack
from app.packs.models import EvalCase

ROOT = Path(__file__).resolve().parents[3]
PACKS = sorted(path for path in (ROOT / "packs").iterdir() if path.is_dir() and not path.name.startswith("_"))


def _dbt_mart_catalog() -> FakeCatalog:
    tables: dict[str, set[str]] = {}
    for path in (ROOT / "dbt" / "models").rglob("*.yml"):
        if "marts" not in path.parts:
            continue
        for model in yaml.safe_load(path.read_text(encoding="utf-8")).get("models", []):
            tables[model["name"]] = {column["name"] for column in model.get("columns", [])}
    return FakeCatalog(tables)


def test_repository_has_a_pack():
    assert PACKS


@pytest.mark.parametrize("pack_dir", PACKS, ids=lambda path: path.name)
def test_pack_loads_against_the_marts(pack_dir: Path):
    load_pack(pack_dir, catalog=_dbt_mart_catalog())


@pytest.mark.parametrize("pack_dir", PACKS, ids=lambda path: path.name)
def test_eval_covers_every_required_category(pack_dir: Path):
    pack = load_pack(pack_dir)
    categories = set(typing.get_args(EvalCase.model_fields["category"].annotation))

    assert {case.category for case in pack.eval.cases} == categories
