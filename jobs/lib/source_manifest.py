"""Parse and validate source manifests under ``jobs/sources``.

A manifest declares one data source of a pack (DECISIONS §4 Data sources):
its ``kind`` (a pinned Hugging Face dataset, PostgreSQL, MySQL/MariaDB,
MongoDB or files in an S3-compatible store), its ``mode`` (``copy`` into
``raw`` or ``live`` through a ClickHouse engine), the ``connection_env``
prefix of the ``.env`` variables its ClickHouse named collection reads, the
dbt tag of the models it feeds, and its tables.

``source.schema.json`` holds the per-file rules. This module adds the checks a
schema cannot make: the name matches the file, table names are unique, a date
range is ordered, and manifests that share a dbt tag declare the same tables,
because they are alternative sources for one set of models. Names, types and
paths are interpolated into SQL, so the schema allows only plain identifiers,
an allowlist of column types and plain object keys.
"""

import json
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import jsonschema
import yaml

SOURCES_DIR = Path(__file__).resolve().parent.parent / "sources"
SCHEMA_PATH = SOURCES_DIR / "source.schema.json"
IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")
HUGGINGFACE = "huggingface"
LIVE_KINDS = frozenset({"postgres", "mysql", "mongodb", "files"})


class ManifestError(ValueError):
    """A source manifest is missing, malformed or conflicts with another."""


@dataclass(frozen=True)
class DateRange:
    """Half-open range ``[start, end)`` applied to ``column`` at load time."""

    column: str
    start: str
    end: str


@dataclass(frozen=True)
class ColumnSpec:
    """A declared column of a collection or file: its name and ClickHouse type."""

    name: str
    type: str


@dataclass(frozen=True)
class TableSpec:
    name: str
    expected_rows: int | None = None
    file: str | None = None
    format: str | None = None
    # Table in the source database, collection, or object key of a file.
    source: str | None = None
    columns: tuple[ColumnSpec, ...] = ()
    date_range: DateRange | None = None
    card_rows: int | None = None

    @property
    def source_name(self) -> str:
        return self.source or self.name


@dataclass(frozen=True)
class SourceManifest:
    name: str
    dbt_tag: str
    tables: tuple[TableSpec, ...]
    kind: str = HUGGINGFACE
    mode: str = "copy"
    connection_env: str | None = None
    hf_repo: str | None = None
    revision: str | None = None


def load_manifest(name: str, sources_dir: Path = SOURCES_DIR) -> SourceManifest:
    path = sources_dir / f"{name}.yaml"
    if not path.is_file():
        raise ManifestError(f"no manifest for source {name!r} in {sources_dir}")
    manifest = _parse(_read(path), path.name)
    if manifest.name != name:
        raise ManifestError(f"{path.name}: name {manifest.name!r} must match the file name")
    _check_shared_dbt_tag(manifest, path, sources_dir)
    return manifest


def _read(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ManifestError(f"{path.name}: expected a mapping at the top level")
    return data


@cache
def _validator() -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))


def _validate(data: dict, origin: str) -> None:
    errors = [_deepest(error) for error in _validator().iter_errors(data)]
    if errors:
        raise ManifestError(f"{origin}: {_describe(max(errors, key=lambda error: len(error.absolute_path)))}")


def _deepest(error: jsonschema.ValidationError) -> jsonschema.ValidationError:
    """The most specific error under an if/then branch, which names the offending field."""
    while error.context:
        error = max(error.context, key=lambda child: len(child.absolute_path))
    return error


def _describe(error: jsonschema.ValidationError) -> str:
    where = "/".join(str(part) for part in error.absolute_path) or "manifest"
    if error.validator == "pattern" and error.schema.get("pattern") == IDENTIFIER.pattern:
        return f"{where}: {error.instance!r} is not a lower-case identifier"
    return f"{where}: {error.message}"


def _check_kind_keys(data: dict, origin: str) -> None:
    # The schema forbids these keys too, but its error for a forbidden key does not name the key.
    kind = data.get("kind", HUGGINGFACE)
    forbidden = {"connection_env"} if kind == HUGGINGFACE else {"hf_repo", "revision"}
    found = sorted(forbidden & set(data))
    if found:
        raise ManifestError(f"{origin}: {found} not allowed for kind {kind!r}")


def _parse(data: dict, origin: str) -> SourceManifest:
    _check_kind_keys(data, origin)
    _validate(data, origin)
    tables = tuple(_parse_table(item, f"{origin}: table {item['name']!r}") for item in data["tables"])
    names = [table.name for table in tables]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise ManifestError(f"{origin}: duplicate table names {duplicates}")
    return SourceManifest(
        name=data["name"],
        dbt_tag=data["dbt_tag"],
        tables=tables,
        kind=data.get("kind", HUGGINGFACE),
        mode=data.get("mode", "copy"),
        connection_env=data.get("connection_env"),
        hf_repo=data.get("hf_repo"),
        revision=data.get("revision"),
    )


def _parse_table(item: dict, where: str) -> TableSpec:
    date_range = None
    if "date_range" in item:
        value = item["date_range"]
        if value["start"] >= value["end"]:
            raise ManifestError(f"{where}: date_range start must be before end")
        if item["card_rows"] < item["expected_rows"]:
            raise ManifestError(f"{where}: card_rows must be at least expected_rows")
        date_range = DateRange(column=value["column"], start=value["start"], end=value["end"])
    return TableSpec(
        name=item["name"],
        expected_rows=item.get("expected_rows"),
        file=item.get("file"),
        format=item.get("format"),
        source=item.get("source", item.get("path")),
        columns=tuple(ColumnSpec(column["name"], column["type"]) for column in item.get("columns", ())),
        date_range=date_range,
        card_rows=item.get("card_rows"),
    )


def _check_shared_dbt_tag(manifest: SourceManifest, path: Path, sources_dir: Path) -> None:
    tables = sorted(table.name for table in manifest.tables)
    for other in sorted(sources_dir.glob("*.yaml")):
        if other == path:
            continue
        data = _read(other)
        if data.get("dbt_tag") != manifest.dbt_tag:
            continue
        other_tables = sorted(item.get("name") for item in data.get("tables") or [] if isinstance(item, dict))
        if other_tables != tables:
            raise ManifestError(
                f"dbt_tag {manifest.dbt_tag!r} is also used by {other.name} with tables {other_tables}; "
                f"sources that feed one set of models must declare the same tables {tables}"
            )
