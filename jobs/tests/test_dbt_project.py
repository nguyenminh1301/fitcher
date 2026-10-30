import re
from pathlib import Path

import yaml

from jobs.lib.manifest import SOURCES_DIR, load_manifest

DBT_DIR = Path(__file__).resolve().parents[2] / "dbt"


def test_no_model_sets_alias():
    # Every pack shares one dbt project, so dbt itself rejects two models that
    # resolve to the same relation; an alias would bypass that protection.
    files = [DBT_DIR / "dbt_project.yml", *DBT_DIR.joinpath("models").rglob("*.*")]
    offenders = [f.name for f in files if re.search(r"\balias\s*[:=]", f.read_text(encoding="utf-8"))]
    assert offenders == []


def test_each_source_folder_is_tagged_with_its_dbt_tag():
    project = yaml.safe_load((DBT_DIR / "dbt_project.yml").read_text(encoding="utf-8"))
    models = project["models"]["fitcher"]
    for path in sorted(SOURCES_DIR.glob("*.yaml")):
        manifest = load_manifest(path.stem)
        assert manifest.dbt_tag in models[manifest.name]["+tags"]
        assert (DBT_DIR / "models" / manifest.name).is_dir()
