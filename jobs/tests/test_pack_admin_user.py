"""The ClickHouse user the api builds instant pack marts and applies pack policies as (DECISIONS §9, §11 step 0)."""

from pathlib import Path
import xml.etree.ElementTree as ElementTree

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _user():
    return ElementTree.parse(ROOT / "infra" / "clickhouse" / "users.d" / "pack_admin.xml").getroot().find("users/pack_admin")


def _grants() -> list[str]:
    return [query.text.strip() for query in _user().findall("grants/query")]


def test_pack_admin_reads_its_password_from_the_environment():
    assert _user().find("password").get("from_env") == "CLICKHOUSE_PACK_ADMIN_PASSWORD"


def test_pack_admin_can_grant_marts_only_and_reads_raw_and_src_without_the_grant_option():
    grants = _grants()
    with_option = [grant for grant in grants if "WITH GRANT OPTION" in grant]
    assert with_option == ["GRANT SELECT, SHOW TABLES, CREATE VIEW, DROP VIEW ON marts.* WITH GRANT OPTION"]
    assert "GRANT SELECT ON raw.*" in grants and "GRANT SELECT ON src_*.*" in grants
    text = " ".join(grants)
    for forbidden in ("agent_logs", "data_meta", "NAMED COLLECTION", "SECRETS", "ACCESS MANAGEMENT", "ON *.* WITH"):
        assert forbidden not in text


def test_compose_mounts_the_user_and_gives_its_password_to_clickhouse_and_the_api_only():
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))["services"]
    for name, service in compose.items():
        environment = service.get("environment") or {}
        assert ("CLICKHOUSE_PACK_ADMIN_PASSWORD" in environment) == (name in ("clickhouse", "api")), name
    assert "users.d/pack_admin.xml" in " ".join(compose["clickhouse"]["volumes"])
    values = dict(line.split("=", 1) for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
                  if line and not line.startswith("#"))
    assert values["CLICKHOUSE_PACK_ADMIN_PASSWORD"] == "change-me"


def test_pack_admin_takes_its_privileges_from_grants_only():
    # ClickHouse refuses to start when a user with <grants> also sets another access control setting.
    assert _user().find("access_management") is None
