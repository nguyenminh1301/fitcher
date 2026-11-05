"""Every non-Hugging Face source is wired the same way through the repository.

A manifest's ``connection_env`` prefix must name the variables that its
ClickHouse named collection reads, the clickhouse service must receive them,
and ``.env.example`` must list them with placeholders only.
"""

import re
import xml.etree.ElementTree as ElementTree
from pathlib import Path

import yaml

from jobs.lib.source_manifest import HUGGINGFACE, SOURCES_DIR, load_manifest

ROOT = Path(__file__).resolve().parents[2]
SETTINGS = ("HOST", "PORT", "DATABASE", "USER", "PASSWORD")


def _sources():
    manifests = [load_manifest(path.stem) for path in sorted(SOURCES_DIR.glob("*.yaml"))]
    return [manifest for manifest in manifests if manifest.kind != HUGGINGFACE]


def _collections() -> dict[str, dict[str, str]]:
    tree = ElementTree.parse(ROOT / "infra" / "clickhouse" / "config.d" / "sources.xml")
    return {
        collection.tag: {key.tag: key.get("from_env") for key in collection}
        for collection in tree.getroot().find("named_collections")
    }


def _example_env() -> dict[str, str]:
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    return dict(line.split("=", 1) for line in lines if line and not line.startswith("#"))


def test_fixture_sources_cover_every_kind():
    assert {manifest.kind for manifest in _sources()} == {"postgres", "mysql", "mongodb", "files"}


def test_each_source_has_a_named_collection_that_reads_only_its_variables():
    collections = _collections()
    for manifest in _sources():
        values = collections[manifest.name]
        assert all(value and value.startswith(f"{manifest.connection_env}_") for value in values.values())
        assert f"{manifest.connection_env}_PASSWORD" in values.values()
        # No value is written into the file itself.
        assert all(key.text is None for key in ElementTree.parse(
            ROOT / "infra" / "clickhouse" / "config.d" / "sources.xml"
        ).getroot().iter() if key.get("from_env"))


def test_clickhouse_receives_and_env_example_lists_every_source_setting():
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    clickhouse_env = compose["services"]["clickhouse"]["environment"]
    example = _example_env()
    for manifest in _sources():
        for setting in SETTINGS:
            name = f"{manifest.connection_env}_{setting}"
            assert name in example, name
        for value in _collections()[manifest.name].values():
            assert value in clickhouse_env, value
        assert example[f"{manifest.connection_env}_PASSWORD"] == "change-me"


def test_only_clickhouse_and_the_fixture_itself_receive_a_source_password():
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    for manifest in _sources():
        password = f"{manifest.connection_env}_PASSWORD"
        holders = sorted(
            name for name, service in compose["services"].items()
            if any(re.search(rf"\b{password}\b", f"{key}={value}") for key, value in (service.get("environment") or {}).items())
        )
        assert holders[0] == "clickhouse" and len(holders) == 2 and holders[1].endswith("-fixture"), holders


def test_the_api_and_jobs_never_receive_a_source_credential():
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    for service in ("api", "jobs", "web", "litellm"):
        environment = compose["services"][service].get("environment") or {}
        assert not any(key.startswith("FIXTURE_") for key in environment), service
