"""Profile the marts a pack reads into ``build/packs/<pack>/profile.json``.

Run with ``docker compose run --rm jobs python -m jobs.profile --pack <name> [--tables a,b]``.
The tables default to the dataset ids in the pack's ``datasets.yaml``; a new
pack without datasets names its marts with ``--tables``. The profile is
deterministic (no LLM call) and is the evidence the drafter cites; see
``app.onboarding.profiler`` for its schema.
"""

import argparse
import json
import os
from pathlib import Path
import sys

from clickhouse_connect.driver.exceptions import Error as ClickHouseError
import yaml

from app.config import SettingsError, load_settings
from app.onboarding.profiler import profile_marts, profile_path
from app.packs.compiler import CompileError
from jobs.compile_pack import ClickHouseWarehouse
from jobs.lib.clickhouse import admin_client

ROOT = Path(__file__).resolve().parents[1]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pack", required=True, help="pack directory name under --packs-dir")
    parser.add_argument("--packs-dir", type=Path, default=ROOT / "packs")
    parser.add_argument("--tables", help="comma-separated marts tables; default: the pack's dataset ids")
    return parser.parse_args(argv)


def pack_tables(pack_dir: Path) -> list[str]:
    path = pack_dir / "datasets.yaml"
    if not path.is_file():
        return []
    content = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [item["id"] for item in content.get("datasets") or [] if isinstance(item, dict) and item.get("id")]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    tables = [table.strip() for table in args.tables.split(",") if table.strip()] if args.tables else pack_tables(
        args.packs_dir / args.pack
    )
    if not tables:
        print(f"pack {args.pack} lists no datasets; name its marts tables with --tables", file=sys.stderr)
        return 2
    try:
        settings = load_settings()
        profile = profile_marts(ClickHouseWarehouse(admin_client()), tables)
    except (CompileError, SettingsError, ClickHouseError) as error:
        print(error, file=sys.stderr)
        return 1
    target = profile_path(Path(settings.compiled_pack_dir), args.pack)
    target.parent.mkdir(parents=True, exist_ok=True)
    staged = target.with_suffix(".json.tmp")
    staged.write_bytes(json.dumps(profile, indent=2, ensure_ascii=False).encode("utf-8"))
    os.replace(staged, target)
    print(f"Profiled {len(tables)} tables of pack {args.pack} into {target}:")
    for table, facts in profile["tables"].items():
        print(f"  {table}: {facts['rows']} rows, {len(facts['columns'])} columns")
    print(f"  join candidates: {len(profile['join_candidates'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
