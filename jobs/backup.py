"""``fitcher backup --output /data/backups/<name>``: one archive of the instance (DECISIONS §3).

The archive ``<name>.tar.gz`` holds a ClickHouse ``BACKUP`` of every user
database, an online copy of the app state (``app.db``) and the packs,
compiled packs, documents, uploaded files and ClickHouse passwords of the data
directory. Both copies are taken while ``one_job``'s lock is held, so no sync,
compile or eval of the api changes them in between; questions still run and
only add conversation rows. ``--app-only`` leaves ClickHouse out: the
ClickHouse copy doubles its disk use while it is written, and an external
ClickHouse (``CLICKHOUSE_URL``) writes it on its own disk. The instance's
secret key, which decrypts provider keys and source passwords, is in the
archive only with ``--include-secret-key``: anyone with that archive can then
read them. ``jobs.restore`` restores an archive into an empty data directory.
"""

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import tarfile
import tempfile

ARCHIVE_VERSION = 1
# Data directory entries copied as they are; models are downloaded again and run files are rebuilt at start.
COPIED = ("packs", "compiled", "documents", "sources", "secrets/clickhouse.env")
SKIPPED_DATABASES = ("system", "information_schema", "INFORMATION_SCHEMA")
CLICKHOUSE_BACKUPS = Path("backups") / "clickhouse"
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")


class BackupError(RuntimeError):
    pass


def data_dir() -> Path:
    return Path(os.environ.get("FITCHER_DATA_DIR") or "/data")


def archive_path(output: str) -> Path:
    path = Path(output)
    name = path.name.removesuffix(".tar.gz")
    if not _NAME.fullmatch(name):
        raise BackupError(f"the backup name {name!r} must be letters, digits, '.', '_' or '-'")
    return path.with_name(f"{name}.tar.gz")


def backup_sql(file: str) -> str:
    return f"BACKUP ALL EXCEPT DATABASES {', '.join(SKIPPED_DATABASES)} TO File('{file}')"


def copy_state(source: Path, target: Path) -> None:
    """An online copy of the SQLite app state, consistent while the api keeps writing."""
    with sqlite3.connect(source) as live, sqlite3.connect(target) as copy:
        live.backup(copy)


def write_archive(
    root: Path, output: Path, clickhouse, *, include_secret_key: bool, clock=lambda: datetime.now(UTC),
) -> Path:
    """Write the archive; ``clickhouse`` is the admin client, or None for the app state and packs alone."""
    from app.api.limits import one_job
    from app.state.secrets import KEY_FILE

    if output.exists():
        raise BackupError(f"{output} already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    name = output.name.removesuffix(".tar.gz")
    clickhouse_file = root / CLICKHOUSE_BACKUPS / f"{name}.zip"
    with tempfile.TemporaryDirectory(dir=output.parent) as scratch:
        state_copy = Path(scratch) / "app.db"
        with one_job():
            if (root / "app.db").exists():
                copy_state(root / "app.db", state_copy)
            if clickhouse is not None:
                clickhouse_file.parent.mkdir(parents=True, exist_ok=True)
                clickhouse.command(backup_sql(str(clickhouse_file)))
        manifest = {"version": ARCHIVE_VERSION, "created_at": clock().isoformat(),
                    "clickhouse": clickhouse_file.name if clickhouse is not None else None,
                    "secret_key": include_secret_key}
        manifest_file = Path(scratch) / "manifest.json"
        manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        partial = output.with_name(output.name + ".partial")
        try:
            with tarfile.open(partial, "w:gz") as archive:
                archive.add(manifest_file, "manifest.json")
                if state_copy.exists():
                    archive.add(state_copy, "app.db")
                for entry in COPIED:
                    if (root / entry).exists():
                        archive.add(root / entry, entry)
                if clickhouse is not None:
                    archive.add(clickhouse_file, f"clickhouse/{clickhouse_file.name}")
                if include_secret_key and (root / KEY_FILE).exists():
                    archive.add(root / KEY_FILE, KEY_FILE)
            os.replace(partial, output)
        finally:
            partial.unlink(missing_ok=True)
            if clickhouse is not None and clickhouse_file.exists():
                if clickhouse_file.is_dir():
                    shutil.rmtree(clickhouse_file)
                else:
                    clickhouse_file.unlink()
    os.chmod(output, 0o600)
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fitcher backup", description=__doc__.split("\n\n")[0])
    parser.add_argument("--output", required=True, help="the archive to write, such as /data/backups/<name>")
    parser.add_argument("--app-only", action="store_true", help="leave the ClickHouse data out")
    parser.add_argument("--include-secret-key", action="store_true",
                        help="add the secret key: whoever holds the archive can read provider keys and source passwords")
    args = parser.parse_args(argv)
    try:
        output = archive_path(args.output)
        clickhouse = None
        if not args.app_only:
            if os.environ.get("CLICKHOUSE_URL"):
                raise BackupError("an external ClickHouse keeps its own backups; back it up there and use --app-only here")
            from jobs.lib.clickhouse import admin_client
            clickhouse = admin_client()
        if args.include_secret_key:
            print("backup: the archive contains the secret key; keep it as safe as the data volume", file=sys.stderr)
        written = write_archive(data_dir(), output, clickhouse, include_secret_key=args.include_secret_key)
    except (BackupError, OSError, RuntimeError) as error:
        print(f"backup: {error}", file=sys.stderr)
        return 1
    print(f"backup: wrote {written}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
