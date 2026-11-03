"""The JSON Schemas the web app's contract types are generated from match the Pydantic models (DECISIONS §7)."""

import json
from pathlib import Path

import pytest

from scripts.generate_contract_types import CONTRACTS

SCHEMAS = Path(__file__).resolve().parents[2] / "web" / "lib" / "contracts" / "schemas"


@pytest.mark.parametrize("name", sorted(CONTRACTS))
def test_committed_contract_schemas_match_the_models(name):
    model, mode = CONTRACTS[name]
    committed = json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))

    assert committed == model.model_json_schema(mode=mode), "run python scripts/generate_contract_types.py, then npm run contracts:generate"


def test_every_schema_file_is_a_contract():
    assert sorted(path.name.removesuffix(".schema.json") for path in SCHEMAS.glob("*.schema.json")) == sorted(CONTRACTS)


def test_stream_events_require_their_discriminator_and_trace_id():
    schema = CONTRACTS["ask_event"][0].model_json_schema(mode="serialization")

    for name, definition in schema["$defs"].items():
        if name.endswith("Event"):
            assert {"event", "trace_id"} <= set(definition["required"]), name
