"""Shared fixtures for the Domain Pack tests.

Tests copy the synthetic pack under ``fixtures/packs/minimal`` into a temporary
directory and edit one YAML file at a time to produce each failure.
"""

from collections.abc import Callable
import os
from pathlib import Path
import shutil
from typing import Any

import pytest
import yaml

from app.packs.loader import read_yaml

# Tests that import litellm read its bundled price table instead of downloading one.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

FIXTURE_PACK = Path(__file__).parent / "fixtures" / "packs" / "minimal"
SCHEMA_DIR = Path(__file__).resolve().parents[3] / "packs" / "_schema"


class FakeCatalog:
    """Warehouse catalog backed by a table -> column names mapping."""

    def __init__(self, tables: dict[str, set[str]]):
        self.tables = tables

    def table_columns(self, table: str) -> set[str] | None:
        return self.tables.get(table)


def fixture_catalog() -> FakeCatalog:
    """A catalog that matches the fixture pack's datasets exactly."""
    data = yaml.safe_load((FIXTURE_PACK / "datasets.yaml").read_text(encoding="utf-8"))
    return FakeCatalog({item["id"]: {column["name"] for column in item["columns"]} for item in data["datasets"]})


@pytest.fixture
def pack_dir(tmp_path: Path) -> Path:
    target = tmp_path / FIXTURE_PACK.name
    shutil.copytree(FIXTURE_PACK, target)
    return target


@pytest.fixture
def edit_pack(pack_dir: Path) -> Callable[[str, Callable[[Any], None]], None]:
    """Return a function that applies an in-place change to one pack file."""

    def edit(file_name: str, change: Callable[[Any], None]) -> None:
        path = pack_dir / file_name
        data = read_yaml(path)
        change(data)
        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")

    return edit


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Keep the app state of any test that starts the app out of the real data directory."""
    from app.state.db import reset_shared_state

    monkeypatch.setenv("FITCHER_DATA_DIR", str(tmp_path / "fitcher-data"))
    reset_shared_state()
    yield
    reset_shared_state()
