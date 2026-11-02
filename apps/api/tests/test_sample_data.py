"""Each pack's sample data for the web app's sample-data mode (DECISIONS §15) is valid and uses the pack's roles."""

import importlib.util
import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

from app.packs.loader import read_yaml

ROOT = Path(__file__).resolve().parents[3]
PACKS = ROOT / "packs"
CONSOLE_ROLES = {"pack_reviewer", "admin"}
SAMPLE_FILES = sorted(PACKS.glob("*/sample_data/*.json"))


def _schema(name: str) -> Draft202012Validator:
    return Draft202012Validator(json.loads((PACKS / "_schema" / f"sample_{name}.schema.json").read_text(encoding="utf-8")))


def _pack_roles(pack_dir: Path) -> set[str]:
    return {role["id"] for role in read_yaml(pack_dir / "policies.yaml")["roles"]}


def test_some_pack_has_sample_data():
    assert SAMPLE_FILES


@pytest.mark.parametrize("path", SAMPLE_FILES, ids=lambda path: f"{path.parent.parent.name}/{path.name}")
def test_every_pack_sample_file_matches_its_schema(path):
    errors = [f"{list(error.absolute_path)}: {error.message}" for error in _schema(path.stem).iter_errors(json.loads(path.read_text(encoding="utf-8")))]

    assert errors == []


@pytest.mark.parametrize("pack_dir", sorted({path.parent.parent for path in SAMPLE_FILES}), ids=lambda path: path.name)
def test_sample_data_names_only_the_packs_roles(pack_dir):
    roles = _pack_roles(pack_dir)
    console = json.loads((pack_dir / "sample_data" / "console.json").read_text(encoding="utf-8"))
    scenarios = json.loads((pack_dir / "sample_data" / "scenarios.json").read_text(encoding="utf-8"))

    assert set(console["pack_roles"]) == roles
    assert {role for identity in console["identities"] for role in identity["roles"]} <= roles | CONSOLE_ROLES
    assert {role for scenario in scenarios["scenarios"] for role in scenario["allowed_roles"]} <= roles
    assert {role for user in console["users"] for role in user["roles"]} <= roles | CONSOLE_ROLES


def test_isolation_check_also_scans_the_web_app(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("check_pack_isolation", ROOT / "scripts" / "check_pack_isolation.py")
    check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check)
    web = tmp_path / "web"
    (web / "lib").mkdir(parents=True)
    (web / "lib" / "chart.ts").write_text("const metric = 'refund_total';\n", encoding="utf-8")
    (web / "node_modules").mkdir()
    (web / "node_modules" / "dep.js").write_text("refund_total\n", encoding="utf-8")
    monkeypatch.setattr(check, "WEB", web)

    failures = check.web_failures(check.name_pattern({"refund_total"}))

    assert [failure.split(": ")[-1] for failure in failures] == ["pack name 'refund_total'"]
