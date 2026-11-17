"""``fitcher restore --input <archive>``: restore a ``jobs.backup`` archive into an empty data directory.

Run it before the instance's first start on a new volume:
``docker run --rm --entrypoint fitcher -v <volume>:/data -v <dir>:/backups <image> restore --input /backups/<name>.tar.gz``.
A data directory holding anything other than ``backups`` is refused, so a
restore never mixes two instances. The files are extracted at once; the
ClickHouse copy is restored by ``--finish``, which the image's migrate step
runs at the next start, after ClickHouse answers and before the schema
changes newer than the backup are applied. Without the secret key in the
archive the stored secrets cannot be read, so they are removed: provider
keys and source passwords are entered again after the restore.
"""

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
import tarfile

from jobs.backup import ARCHIVE_VERSION, CLICKHOUSE_BACKUPS, data_dir

PENDING = "restore.pending"
ALLOWED_ENTRIES = {"backups", "lost+found"}


class RestoreError(RuntimeError):
    pass


def restore_sql(file: str) -> str:
    # The backup holds the fitcher databases and the access entities created with SQL; ALL restores both.
    return f"RESTORE ALL FROM File('{file}')"


def extract(archive_file: Path, root: Path) -> dict:
    from app.state.secrets import KEY_FILE

    present = sorted(entry.name for entry in root.iterdir() if entry.name not in ALLOWED_ENTRIES) if root.exists() else []
    if present:
        raise RestoreError(f"{root} is not empty ({', '.join(present[:5])}); restore into a new volume")
    root.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_file, "r:gz") as archive:
        try:
            manifest = json.load(archive.extractfile("manifest.json"))
        except (KeyError, TypeError, ValueError):
            raise RestoreError(f"{archive_file} is not a fitcher backup") from None
        if manifest.get("version") != ARCHIVE_VERSION:
            raise RestoreError(f"backup version {manifest.get('version')} is not supported by this image")
        for member in archive.getmembers():
            if member.name == "manifest.json":
                continue
            target = member.name
            if member.name.startswith("clickhouse/"):
                target = str(CLICKHOUSE_BACKUPS / member.name.removeprefix("clickhouse/"))
            member.name = target
            # The data filter refuses absolute paths, '..', links out of the directory and special files.
            archive.extract(member, root, filter="data")
    if not manifest.get("secret_key"):
        (root / KEY_FILE).unlink(missing_ok=True)
        if (root / "app.db").exists():
            with sqlite3.connect(root / "app.db") as state:
                if state.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'secrets'").fetchone():
                    state.execute("DELETE FROM secrets")
    if (root / "secrets").exists():
        os.chmod(root / "secrets", 0o700)
    if manifest.get("clickhouse"):
        (root / PENDING).write_text(manifest["clickhouse"], encoding="utf-8")
    return manifest


def finish(root: Path, clickhouse) -> bool:
    """Restore the pending ClickHouse copy; False when there is none."""
    pending = root / PENDING
    if not pending.exists():
        return False
    file = root / CLICKHOUSE_BACKUPS / pending.read_text(encoding="utf-8").strip()
    clickhouse.command(restore_sql(str(file)))
    pending.unlink()
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fitcher restore", description=__doc__.split("\n\n")[0])
    parser.add_argument("--input", help="the archive written by fitcher backup")
    parser.add_argument("--finish", action="store_true", help="restore the pending ClickHouse copy (run at start)")
    args = parser.parse_args(argv)
    try:
        if args.finish:
            if (data_dir() / PENDING).exists():
                from jobs.lib.clickhouse import admin_client
                finish(data_dir(), admin_client())
                print("restore: ClickHouse data restored")
            return 0
        if not args.input:
            parser.error("--input is required")
        manifest = extract(Path(args.input), data_dir())
    except (RestoreError, OSError, RuntimeError, tarfile.TarError) as error:
        print(f"restore: {error}", file=sys.stderr)
        return 1
    if not manifest.get("secret_key"):
        print("restore: the backup holds no secret key; enter provider keys and source passwords again", file=sys.stderr)
    print("restore: files restored; start the instance to restore ClickHouse" if manifest.get("clickhouse")
          else "restore: files restored; start the instance")
    return 0


if __name__ == "__main__":
    sys.exit(main())
