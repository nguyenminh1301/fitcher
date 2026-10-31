"""Load a Domain Pack directory and validate it.

Loading reads the eight YAML files, validates each against its JSON Schema in
``packs/_schema`` and builds the typed models. Every problem is collected and
reported at once, each naming the file, the item path and the field.
"""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
import json
from pathlib import Path
import re

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
import yaml

from app.packs.models import PACK_FILES, Pack


@dataclass(frozen=True)
class PackIssue:
    file: str
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.file}: {self.path}: {self.message}" if self.path else f"{self.file}: {self.message}"


class PackValidationError(Exception):
    def __init__(self, pack_dir: Path, issues: list[PackIssue]):
        self.issues = issues
        super().__init__(f"Pack {pack_dir.name} is invalid:\n" + "\n".join(f"  {issue}" for issue in issues))


class _PackYamlLoader(yaml.SafeLoader):
    """SafeLoader with YAML 1.2 scalars: dates stay strings and only true/false are booleans.

    YAML 1.1 would read a key such as ``on`` as a boolean and an unquoted date
    as a date object, neither of which the JSON Schemas accept.
    """


_PackYamlLoader.yaml_implicit_resolvers = {
    first: [
        (tag, pattern) for tag, pattern in resolvers
        if tag not in ("tag:yaml.org,2002:timestamp", "tag:yaml.org,2002:bool")
    ]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_PackYamlLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"), list("tTfF")
)


def item_path(parts: Iterable[str | int]) -> str:
    """Format a path such as ``metrics[0].unit``."""
    text = ""
    for part in parts:
        if isinstance(part, int):
            text += f"[{part}]"
        else:
            text += f".{part}" if text else part
    return text


def _validators(schema_dir: Path) -> dict[str, Draft202012Validator]:
    schemas = {path.name: json.loads(path.read_text(encoding="utf-8")) for path in schema_dir.glob("*.schema.json")}
    registry = Registry().with_resources((name, Resource.from_contents(schema)) for name, schema in schemas.items())
    return {
        file: Draft202012Validator(schemas[file.removesuffix(".yaml") + ".schema.json"], registry=registry)
        for file in PACK_FILES
    }


def _schema_issues(file: str, data: object, validator: Draft202012Validator) -> Iterator[PackIssue]:
    for error in validator.iter_errors(data):
        path = list(error.absolute_path)
        if error.validator == "required" and isinstance(error.instance, dict):
            for field in error.validator_value:
                if field not in error.instance:
                    yield PackIssue(file, item_path([*path, field]), "required field is missing")
        elif error.validator == "additionalProperties" and isinstance(error.instance, dict):
            for field in sorted(set(error.instance) - set(error.schema.get("properties", {}))):
                yield PackIssue(file, item_path([*path, field]), "unknown field")
        else:
            yield PackIssue(file, item_path(path), error.message)


def read_yaml(path: Path) -> object:
    """Parse one pack file with the pack YAML rules."""
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_PackYamlLoader)  # noqa: S506 - SafeLoader subclass


def load_pack(pack_dir: Path, *, schema_dir: Path | None = None) -> Pack:
    """Load and validate the pack in ``pack_dir``; raise PackValidationError listing every problem."""
    validators = _validators(schema_dir or pack_dir.parent / "_schema")
    contents: dict[str, object] = {}
    issues: list[PackIssue] = []
    for file, validator in validators.items():
        path = pack_dir / file
        if not path.is_file():
            issues.append(PackIssue(file, "", "file is missing"))
            continue
        try:
            data = read_yaml(path)
        except yaml.YAMLError as error:
            issues.append(PackIssue(file, "", "invalid YAML: " + " ".join(str(error).split())))
            continue
        issues.extend(sorted(dict.fromkeys(_schema_issues(file, data, validator)), key=lambda issue: issue.path))
        contents[file.removesuffix(".yaml")] = data
    if issues:
        raise PackValidationError(pack_dir, issues)
    return Pack(name=pack_dir.name, **contents)
