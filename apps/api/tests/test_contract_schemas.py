"""The JSON Schemas the web app's contract types are generated from match the Pydantic models (DECISIONS §7)."""

import json
from pathlib import Path

import pytest

from app.contracts.query_spec import QuerySpec
from app.contracts.result import Result

SCHEMAS = Path(__file__).resolve().parents[2] / "web" / "lib" / "contracts" / "schemas"


@pytest.mark.parametrize(("model", "name"), [(QuerySpec, "query_spec"), (Result, "result")])
def test_committed_contract_schemas_match_the_models(model, name):
    committed = json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))

    assert committed == model.model_json_schema(), f"run python scripts/generate_contract_types.py, then npm run contracts:generate"
