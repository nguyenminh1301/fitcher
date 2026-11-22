"""The ClickHouse user and storage behind the Sources page hold a source credential and never reveal it (DECISIONS §4, §9)."""

from pathlib import Path
import xml.etree.ElementTree as ElementTree

import yaml

ROOT = Path(__file__).resolve().parents[2]
CLICKHOUSE = ROOT / "infra" / "clickhouse"


def _user():
    return ElementTree.parse(CLICKHOUSE / "users.d" / "source_admin.xml").getroot().find("users/source_admin")


def _grants() -> list[str]:
    return [query.text.strip() for query in _user().findall("grants/query")]


def test_source_admin_reads_its_password_from_the_environment():
    assert _user().find("password").get("from_env") == "CLICKHOUSE_SOURCE_ADMIN_PASSWORD"


def test_source_admin_manages_named_collections_but_cannot_show_their_secrets():
    text = " ".join(_grants()).upper()
    for need in ("CREATE NAMED COLLECTION", "ALTER NAMED COLLECTION", "DROP NAMED COLLECTION", "NAMED COLLECTION ON *"):
        assert need in text
    assert "SECRETS" not in text
    assert _user().find("show_named_collections_secrets") is None
    assert _user().find("named_collection_control") is None, "that flag also grants the secrets"


def test_source_admin_writes_only_raw_and_the_src_databases_and_reads_no_mart():
    grants = [grant for grant in _grants() if " ON " in grant]
    data_grants = [grant for grant in grants if "SELECT" in grant and "system" not in grant]
    assert data_grants == [
        "GRANT SELECT, INSERT, CREATE TABLE, DROP TABLE ON raw.*",
        "GRANT SELECT, INSERT, CREATE DATABASE, CREATE TABLE, DROP TABLE, DROP DATABASE ON src_*.*",
    ]
    assert "GRANT SHOW TABLES ON marts.*" in grants


def test_named_collections_are_stored_encrypted_with_a_key_from_the_environment():
    storage = ElementTree.parse(CLICKHOUSE / "config.d" / "named_collections_storage.xml").getroot().find(
        "named_collections_storage")
    assert storage.findtext("type") == "local_encrypted"
    assert storage.findtext("algorithm") == "aes_256_ctr"
    assert storage.find("key_hex").get("from_env") == "CLICKHOUSE_NAMED_COLLECTIONS_KEY"
    assert storage.find("key_hex").text is None, "a key is never written into the file"


def test_compose_gives_clickhouse_the_key_and_only_the_api_the_user_password():
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))["services"]
    assert "CLICKHOUSE_NAMED_COLLECTIONS_KEY" in compose["clickhouse"]["environment"]
    assert "CLICKHOUSE_SOURCE_ADMIN_PASSWORD" in compose["clickhouse"]["environment"]
    for name, service in compose.items():
        environment = service.get("environment") or {}
        assert ("CLICKHOUSE_NAMED_COLLECTIONS_KEY" in environment) == (name == "clickhouse"), name
        assert ("CLICKHOUSE_SOURCE_ADMIN_PASSWORD" in environment) == (name in ("clickhouse", "api")), name
    mounts = " ".join(compose["clickhouse"]["volumes"])
    assert "users.d/source_admin.xml" in mounts and "config.d/named_collections_storage.xml" in mounts


def test_env_example_lists_both_settings_with_placeholders():
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    values = dict(line.split("=", 1) for line in lines if line and not line.startswith("#"))
    assert values["CLICKHOUSE_SOURCE_ADMIN_PASSWORD"] == "change-me"
    assert values["CLICKHOUSE_NAMED_COLLECTIONS_KEY"] == "change-me"
