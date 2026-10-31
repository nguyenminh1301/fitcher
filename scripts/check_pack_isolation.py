"""Fail when engine code under apps/api names a pack dataset, column or metric.

The engine must stay industry-neutral (DECISIONS §13): every dataset id,
column name and metric id of every pack in packs/ is forbidden anywhere in
apps/api, tests included, as a whole word. Names that the synthetic fixture
packs under apps/api/tests/fixtures/packs also use are exempt, because the
engine tests need them.

Run with ``uv run --project apps/api python scripts/check_pack_isolation.py``.
"""

from pathlib import Path
import re
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / "packs"
ENGINE = ROOT / "apps" / "api"
FIXTURE_PACKS = ENGINE / "tests" / "fixtures" / "packs"
SKIPPED_DIRS = {".venv", "__pycache__", ".pytest_cache", ".ruff_cache"}
SKIPPED_FILES = {"uv.lock"}
TEXT_SUFFIXES = {".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".sql", ""}


def pack_names(pack_dir: Path) -> set[str]:
    names: set[str] = set()
    datasets = yaml.safe_load((pack_dir / "datasets.yaml").read_text(encoding="utf-8"))["datasets"]
    for dataset in datasets:
        names.add(dataset["id"])
        names.update(column["name"] for column in dataset["columns"])
    metrics = yaml.safe_load((pack_dir / "metrics.yaml").read_text(encoding="utf-8"))["metrics"]
    names.update(metric["id"] for metric in metrics)
    return names


def pack_dirs(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(path for path in root.iterdir() if path.is_dir() and not path.name.startswith("_"))


def engine_files() -> list[Path]:
    files = []
    for path in ENGINE.rglob("*"):
        relative = path.relative_to(ENGINE)
        if any(part in SKIPPED_DIRS for part in relative.parts) or not path.is_file():
            continue
        if path.name in SKIPPED_FILES or path.suffix not in TEXT_SUFFIXES or path.is_relative_to(FIXTURE_PACKS):
            continue
        files.append(path)
    return sorted(files)


def main() -> int:
    forbidden: set[str] = set()
    for pack in pack_dirs(PACKS):
        forbidden |= pack_names(pack)
    for fixture in pack_dirs(FIXTURE_PACKS):
        forbidden -= pack_names(fixture)
    if not forbidden:
        print("No pack names to check.")
        return 0
    pattern = re.compile(r"(?<![A-Za-z0-9_])(" + "|".join(sorted(map(re.escape, forbidden), key=len, reverse=True)) + r")(?![A-Za-z0-9_])")
    failures = []
    for path in engine_files():
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
            for match in pattern.finditer(line):
                failures.append(f"{path.relative_to(ROOT).as_posix()}:{number}: pack name '{match.group(1)}'")
    if failures:
        print("Pack names found in engine code:", *failures, sep="\n  ", file=sys.stderr)
        return 1
    print(f"Checked {len(engine_files())} files under apps/api against {len(forbidden)} pack names.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
