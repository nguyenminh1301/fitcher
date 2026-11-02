"""Fail when engine code under apps/api or apps/web names a pack dataset, column or metric.

The engine must stay industry-neutral (DECISIONS §13): every dataset id,
column name and metric id of every pack in packs/ is forbidden anywhere in
apps/api and apps/web, tests included, as a whole word; the web app's sample
data lives in each pack's ``sample_data/`` for this reason. Inside apps/api/tests, names that the
synthetic fixture packs under apps/api/tests/fixtures/packs also use are
exempt, because the engine tests need them; engine code gets no exemption.
Pack files are read with the pack loader's YAML rules.

Run with ``uv run --project apps/api python scripts/check_pack_isolation.py``.
"""

from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / "packs"
ENGINE = ROOT / "apps" / "api"
TESTS = ENGINE / "tests"
WEB = ROOT / "apps" / "web"
sys.path.insert(0, str(ENGINE))

from app.packs.loader import read_yaml  # noqa: E402 - needs apps/api on the path
FIXTURE_PACKS = ENGINE / "tests" / "fixtures" / "packs"
SKIPPED_DIRS = {".venv", "__pycache__", ".pytest_cache", ".ruff_cache", "node_modules", ".next", "public"}
SKIPPED_FILES = {"uv.lock", "package-lock.json"}
TEXT_SUFFIXES = {".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".sql", ""}
WEB_SUFFIXES = {".ts", ".tsx", ".mjs", ".js", ".css", ".json", ".md"}


def pack_names(pack_dir: Path) -> set[str]:
    names: set[str] = set()
    datasets = read_yaml(pack_dir / "datasets.yaml")["datasets"]
    for dataset in datasets:
        names.add(dataset["id"])
        names.update(column["name"] for column in dataset["columns"])
    metrics = read_yaml(pack_dir / "metrics.yaml")["metrics"]
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


def web_files() -> list[Path]:
    if not WEB.is_dir():
        return []
    return sorted(
        path for path in WEB.rglob("*")
        if path.is_file() and path.suffix in WEB_SUFFIXES and path.name not in SKIPPED_FILES
        and not any(part in SKIPPED_DIRS for part in path.relative_to(WEB).parts)
    )


def scan(path: Path, pattern: re.Pattern[str]) -> list[str]:
    where = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.as_posix()
    return [
        f"{where}:{number}: pack name '{match.group(1)}'"
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1)
        for match in pattern.finditer(line)
    ]


def web_failures(pattern: re.Pattern[str] | None) -> list[str]:
    """Pack names in apps/web; the web app has no fixture pack, so nothing is exempt."""
    if pattern is None:
        return []
    return [failure for path in web_files() for failure in scan(path, pattern)]


def name_pattern(names: set[str]) -> re.Pattern[str] | None:
    if not names:
        return None
    alternatives = "|".join(sorted(map(re.escape, names), key=len, reverse=True))
    return re.compile(rf"(?<![A-Za-z0-9_])({alternatives})(?![A-Za-z0-9_])")


def main() -> int:
    forbidden: set[str] = set()
    for pack in pack_dirs(PACKS):
        forbidden |= pack_names(pack)
    fixture_names: set[str] = set()
    for fixture in pack_dirs(FIXTURE_PACKS):
        fixture_names |= pack_names(fixture)
    if not forbidden:
        print("No pack names to check.")
        return 0
    engine_pattern = name_pattern(forbidden)
    test_pattern = name_pattern(forbidden - fixture_names)
    failures = []
    for path in engine_files():
        pattern = test_pattern if path.is_relative_to(TESTS) else engine_pattern
        if pattern is not None:
            failures += scan(path, pattern)
    failures += web_failures(engine_pattern)
    if failures:
        print("Pack names found in engine code:", *failures, sep="\n  ", file=sys.stderr)
        return 1
    print(
        f"Checked {len(engine_files())} files under apps/api and {len(web_files())} under apps/web "
        f"against {len(forbidden)} pack names."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
