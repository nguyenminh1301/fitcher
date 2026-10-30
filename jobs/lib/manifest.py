"""Parse and validate source manifests under ``jobs/sources``.

A manifest names one downloadable source at a pinned revision, the dbt tag
that selects its models, and the tables the loader must publish with their
expected row counts. Table names and the dbt tag are interpolated into SQL
and dbt selectors, so they must be plain lower-case identifiers.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

SOURCES_DIR = Path(__file__).resolve().parent.parent / "sources"
SUPPORTED_FORMATS = {"parquet"}
IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")
SOURCE_KEYS = {"name", "hf_repo", "revision", "dbt_tag", "tables"}
TABLE_KEYS = {"name", "file", "format", "expected_rows", "date_range", "card_rows"}
DATE_RANGE_KEYS = {"column", "start", "end"}


class ManifestError(ValueError):
    """A source manifest is missing, malformed or conflicts with another."""


@dataclass(frozen=True)
class DateRange:
    """Half-open range ``[start, end)`` applied to ``column`` at load time."""

    column: str
    start: str
    end: str


@dataclass(frozen=True)
class TableSpec:
    name: str
    file: str
    format: str
    expected_rows: int
    date_range: DateRange | None = None
    card_rows: int | None = None


@dataclass(frozen=True)
class SourceManifest:
    name: str
    hf_repo: str
    revision: str
    dbt_tag: str
    tables: tuple[TableSpec, ...]


def load_manifest(name: str, sources_dir: Path = SOURCES_DIR) -> SourceManifest:
    path = sources_dir / f"{name}.yaml"
    if not path.is_file():
        raise ManifestError(f"no manifest for source {name!r} in {sources_dir}")
    manifest = _parse(_read(path), path.name)
    if manifest.name != name:
        raise ManifestError(f"{path.name}: name {manifest.name!r} must match the file name")
    _check_unique_dbt_tag(manifest, path, sources_dir)
    return manifest


def _read(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ManifestError(f"{path.name}: expected a mapping at the top level")
    return data


def _parse(data: dict, origin: str) -> SourceManifest:
    _check_keys(data, SOURCE_KEYS, origin)
    for key in ("name", "hf_repo", "revision", "dbt_tag"):
        _require_text(data, key, origin)
    for key in ("name", "dbt_tag"):
        _require_identifier(data[key], key, origin)
    raw_tables = data.get("tables")
    if not isinstance(raw_tables, list) or not raw_tables:
        raise ManifestError(f"{origin}: tables must be a non-empty list")
    tables = tuple(_parse_table(item, origin) for item in raw_tables)
    names = [table.name for table in tables]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise ManifestError(f"{origin}: duplicate table names {duplicates}")
    return SourceManifest(
        name=data["name"],
        hf_repo=data["hf_repo"],
        revision=data["revision"],
        dbt_tag=data["dbt_tag"],
        tables=tables,
    )


def _parse_table(item: object, origin: str) -> TableSpec:
    if not isinstance(item, dict):
        raise ManifestError(f"{origin}: each table must be a mapping")
    where = f"{origin}: table {item.get('name')!r}"
    _check_keys(item, TABLE_KEYS, where)
    for key in ("name", "file", "format"):
        _require_text(item, key, where)
    _require_identifier(item["name"], "name", where)
    if item["format"] not in SUPPORTED_FORMATS:
        raise ManifestError(f"{where}: format {item['format']!r} is not one of {sorted(SUPPORTED_FORMATS)}")
    expected_rows = _require_count(item, "expected_rows", where)
    date_range = None
    card_rows = None
    if "date_range" in item:
        date_range = _parse_date_range(item["date_range"], where)
        card_rows = _require_count(item, "card_rows", where)
        if card_rows < expected_rows:
            raise ManifestError(f"{where}: card_rows must be at least expected_rows")
    elif "card_rows" in item:
        raise ManifestError(f"{where}: card_rows is only valid with date_range")
    return TableSpec(
        name=item["name"],
        file=item["file"],
        format=item["format"],
        expected_rows=expected_rows,
        date_range=date_range,
        card_rows=card_rows,
    )


def _parse_date_range(value: object, where: str) -> DateRange:
    if not isinstance(value, dict):
        raise ManifestError(f"{where}: date_range must be a mapping")
    _check_keys(value, DATE_RANGE_KEYS, f"{where} date_range")
    for key in DATE_RANGE_KEYS:
        _require_text(value, key, f"{where} date_range")
    if value["start"] >= value["end"]:
        raise ManifestError(f"{where}: date_range start must be before end")
    return DateRange(column=value["column"], start=value["start"], end=value["end"])


def _check_unique_dbt_tag(manifest: SourceManifest, path: Path, sources_dir: Path) -> None:
    for other in sorted(sources_dir.glob("*.yaml")):
        if other == path:
            continue
        if _read(other).get("dbt_tag") == manifest.dbt_tag:
            raise ManifestError(f"dbt_tag {manifest.dbt_tag!r} is also used by {other.name}")


def _check_keys(data: dict, allowed: set[str], where: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ManifestError(f"{where}: unknown keys {unknown}")


def _require_text(data: dict, key: str, where: str) -> None:
    if not isinstance(data.get(key), str) or not data[key].strip():
        raise ManifestError(f"{where}: {key} must be a non-empty string")


def _require_identifier(value: str, key: str, where: str) -> None:
    if not IDENTIFIER.match(value):
        raise ManifestError(f"{where}: {key} {value!r} is not a lower-case identifier")


def _require_count(data: dict, key: str, where: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ManifestError(f"{where}: {key} must be a non-negative integer")
    return value
