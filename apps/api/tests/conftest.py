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
# Tests that import litellm directly must not load the repository's .env into the test process.
os.environ.setdefault("LITELLM_MODE", "PRODUCTION")

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
def no_local_model_download(monkeypatch):
    """No test downloads or loads a real local embedding model; a test that needs one passes a fake loader."""
    from app.llm import local_embeddings

    def refuse(name, cache_dir):
        raise AssertionError(f"a test tried to load the local embedding model {name}")

    monkeypatch.setattr(local_embeddings, "_fastembed", refuse)


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Keep the app state of any test that starts the app out of the real data directory."""
    from app.state.db import reset_shared_state

    monkeypatch.setenv("FITCHER_DATA_DIR", str(tmp_path / "fitcher-data"))
    reset_shared_state()
    yield
    reset_shared_state()


@pytest.fixture(autouse=True)
def team_mode(isolated_data_dir):
    """Tests sign users in, so the test app state is in team mode; individual-mode tests set their own mode."""
    from app.state.db import shared_state
    from app.state.settings import Settings

    Settings(shared_state()).set("instance", "mode", "team")
