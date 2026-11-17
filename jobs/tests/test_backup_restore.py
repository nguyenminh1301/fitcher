"""``fitcher backup`` and ``fitcher restore`` on a temporary data directory with a fake ClickHouse."""

import json
from types import SimpleNamespace
from pathlib import Path
import sqlite3
import tarfile

import pytest

from jobs import backup, restore


class FakeClickHouse:
    """Writes the file a BACKUP names, lists two databases and records every command."""

    def __init__(self):
        self.commands = []

    def query(self, sql):
        assert sql == backup.DATABASES_SQL
        return SimpleNamespace(result_rows=[("marts",), ("agent_logs",)])

    def command(self, sql):
        self.commands.append(sql)
        if sql.startswith("BACKUP"):
            Path(sql.split("File('")[1].rstrip("')")).write_bytes(b"clickhouse backup")


def instance(root: Path) -> Path:
    for name, text in {"packs/shop/pack.yaml": "name: shop", "compiled/shop/pack.json": "{}",
                       "secrets/clickhouse.env": "CLICKHOUSE_AGENT_PASSWORD=x", "secrets/admin.env": "ADMIN=y",
                       "secret.key": "a2V5", "models/guard/model.bin": "big"}.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    with sqlite3.connect(root / "app.db") as state:
        state.execute("CREATE TABLE secrets (name TEXT, value BLOB)")
        state.execute("INSERT INTO secrets VALUES ('provider:openai', x'00')")
        state.execute("CREATE TABLE settings (k TEXT)")
        state.execute("INSERT INTO settings VALUES ('mode')")
    return root


def names(archive: Path) -> set[str]:
    with tarfile.open(archive) as opened:
        return {member.name for member in opened.getmembers() if member.isfile()}


def test_a_backup_holds_clickhouse_the_state_and_the_packs_but_not_the_key_or_models(tmp_path, monkeypatch):
    root = instance(tmp_path / "data")
    monkeypatch.setenv("FITCHER_DATA_DIR", str(root))
    clickhouse = FakeClickHouse()

    written = backup.write_archive(root, root / "backups" / "rc.tar.gz", clickhouse, include_secret_key=False)

    assert clickhouse.commands == [
        "BACKUP DATABASE `agent_logs`, DATABASE `marts`, TABLE system.users, TABLE system.roles, "
        "TABLE system.settings_profiles, TABLE system.row_policies, TABLE system.quotas "
        f"TO File('{root / 'backups' / 'clickhouse' / 'rc.zip'}')"
    ]
    assert names(written) == {"manifest.json", "app.db", "packs/shop/pack.yaml", "compiled/shop/pack.json",
                              "secrets/clickhouse.env", "clickhouse/rc.zip"}
    assert not (root / "backups" / "clickhouse" / "rc.zip").exists()
    with pytest.raises(backup.BackupError):
        backup.write_archive(root, written, clickhouse, include_secret_key=False)


def test_the_secret_key_is_in_the_archive_only_when_asked(tmp_path, monkeypatch):
    root = instance(tmp_path / "data")
    monkeypatch.setenv("FITCHER_DATA_DIR", str(root))
    written = backup.write_archive(root, tmp_path / "out" / "k.tar.gz", None, include_secret_key=True)
    assert "secret.key" in names(written) and "clickhouse/k.zip" not in names(written)
    with tarfile.open(written) as opened:
        assert json.load(opened.extractfile("manifest.json"))["secret_key"] is True


def test_a_restore_fills_an_empty_directory_and_restores_clickhouse_at_the_next_start(tmp_path, monkeypatch):
    root = instance(tmp_path / "data")
    monkeypatch.setenv("FITCHER_DATA_DIR", str(root))
    archive = backup.write_archive(root, tmp_path / "rc.tar.gz", FakeClickHouse(), include_secret_key=False)
    target = tmp_path / "new"
    (target / "backups").mkdir(parents=True)

    restore.extract(archive, target)

    assert (target / "packs/shop/pack.yaml").read_text() == "name: shop"
    assert not (target / "secret.key").exists()
    with sqlite3.connect(target / "app.db") as state:
        assert state.execute("SELECT count(*) FROM secrets").fetchone() == (0,)
        assert state.execute("SELECT k FROM settings").fetchall() == [("mode",)]
    clickhouse = FakeClickHouse()
    assert restore.finish(target, clickhouse) is True
    assert clickhouse.commands == [restore.restore_sql(str(target / "backups" / "clickhouse" / "rc.zip"))]
    assert restore.finish(target, clickhouse) is False


def test_a_restore_refuses_a_directory_in_use(tmp_path, monkeypatch):
    root = instance(tmp_path / "data")
    monkeypatch.setenv("FITCHER_DATA_DIR", str(root))
    archive = backup.write_archive(root, tmp_path / "rc.tar.gz", None, include_secret_key=False)
    with pytest.raises(restore.RestoreError, match="not empty"):
        restore.extract(archive, root)


def test_a_restore_refuses_a_member_that_leaves_the_directory(tmp_path):
    evil = tmp_path / "evil.tar.gz"
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"version": backup.ARCHIVE_VERSION}))
    (tmp_path / "payload").write_text("x")
    with tarfile.open(evil, "w:gz") as archive:
        archive.add(manifest, "manifest.json")
        archive.add(tmp_path / "payload", "../escaped")
    with pytest.raises(tarfile.TarError):
        restore.extract(evil, tmp_path / "new")
    assert not (tmp_path / "escaped").exists()


def test_an_unexpected_database_name_is_refused():
    with pytest.raises(backup.BackupError):
        backup.backup_sql("/data/backups/clickhouse/x.zip", ["marts`; DROP"])


def test_a_backup_name_is_checked():
    with pytest.raises(backup.BackupError):
        backup.archive_path("/data/backups/bad name;rm")
    assert backup.archive_path("/data/backups/rc") == Path("/data/backups/rc.tar.gz")
