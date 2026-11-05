import re
from pathlib import Path

import yaml

from jobs.lib.source_manifest import SOURCES_DIR, load_manifest

DBT_DIR = Path(__file__).resolve().parents[2] / "dbt"


def test_no_model_sets_alias():
    # Every pack shares one dbt project, so dbt itself rejects two models that
    # resolve to the same relation; an alias would bypass that protection.
    files = [DBT_DIR / "dbt_project.yml", *DBT_DIR.joinpath("models").rglob("*.*")]
    offenders = [f.name for f in files if re.search(r"\balias\s*[:=]", f.read_text(encoding="utf-8"))]
    assert offenders == []


def test_each_dbt_tag_has_its_tagged_model_folder():
    # Sources that share a dbt tag feed the one folder named after it.
    project = yaml.safe_load((DBT_DIR / "dbt_project.yml").read_text(encoding="utf-8"))
    models = project["models"]["fitcher"]
    for path in sorted(SOURCES_DIR.glob("*.yaml")):
        manifest = load_manifest(path.stem)
        assert manifest.dbt_tag in models[manifest.dbt_tag]["+tags"]
        assert (DBT_DIR / "models" / manifest.dbt_tag).is_dir()


def test_models_of_non_huggingface_sources_read_through_source_table():
    # Their staging must follow the relations jobs.refresh_data passes, never a fixed raw table.
    tags = {load_manifest(p.stem).dbt_tag for p in SOURCES_DIR.glob("*.yaml") if load_manifest(p.stem).kind != "huggingface"}
    for tag in tags:
        staging = sorted((DBT_DIR / "models" / tag / "staging").glob("*.sql"))
        assert staging
        for model in staging:
            text = model.read_text(encoding="utf-8")
            assert "source_table(" in text and "source(" not in text.replace("source_table(", "")
