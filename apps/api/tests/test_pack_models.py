"""The Pydantic pack models stay identical to the JSON Schemas.

The JSON Schemas are the contract and run first; the models must accept the
same fields. The comparison covers object properties, required fields, closed
objects, array items, scalar types and enum values. Value constraints such as
patterns and bounds live in the schemas only.
"""

import json

from conftest import SCHEMA_DIR
import pytest

from app.packs.models import PACK_FILES


def _resolve(node, root, documents):
    while "$ref" in node:
        target, _, pointer = node["$ref"].partition("#")
        document = documents[target] if target else root
        if target:
            root = document
        node = document
        for part in [part for part in pointer.split("/") if part]:
            node = node[part]
    return node, root


def _shape(node, root, documents):
    node, root = _resolve(node, root, documents)
    variants = [variant for variant in node.get("anyOf", []) if variant.get("type") != "null"]
    if len(variants) == 1:
        return _shape(variants[0], root, documents)
    shape = {}
    if "enum" in node:
        shape["enum"] = sorted(node["enum"])
    if "type" in node:
        shape["type"] = node["type"]
    if node.get("type") == "object":
        shape["closed"] = node.get("additionalProperties") is False
        shape["required"] = sorted(node.get("required", []))
        shape["properties"] = {
            name: _shape(child, root, documents) for name, child in node.get("properties", {}).items()
        }
    if node.get("type") == "array":
        shape["items"] = _shape(node["items"], root, documents)
    return shape


def _schema_documents():
    return {path.name: json.loads(path.read_text(encoding="utf-8")) for path in SCHEMA_DIR.glob("*.schema.json")}


@pytest.mark.parametrize("file_name", sorted(PACK_FILES))
def test_model_matches_schema(file_name):
    documents = _schema_documents()
    schema = documents[file_name.replace(".yaml", ".schema.json")]
    model_schema = PACK_FILES[file_name].model_json_schema()

    assert _shape(model_schema, model_schema, {}) == _shape(schema, schema, documents)


def test_every_pack_file_has_a_schema():
    names = {name.replace(".yaml", ".schema.json") for name in PACK_FILES}

    assert names == {path.name for path in SCHEMA_DIR.glob("*.schema.json")} - {"common.schema.json"}
    assert len(PACK_FILES) == 8
