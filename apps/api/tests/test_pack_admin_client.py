"""The api's ClickHouse connection for instant pack marts and policies (infra/clickhouse/users.d/pack_admin.xml)."""

import pytest

from app.onboarding import client as pack_client


def test_the_password_is_required():
    with pytest.raises(RuntimeError, match="CLICKHOUSE_PACK_ADMIN_PASSWORD must be set"):
        pack_client.pack_admin_client({})


def test_connects_as_pack_admin_without_a_session(monkeypatch):
    seen = {}
    monkeypatch.setattr(pack_client.clickhouse_connect, "get_client", lambda **kwargs: seen.update(kwargs) or "client")

    assert pack_client.pack_admin_client({"CLICKHOUSE_PACK_ADMIN_PASSWORD": "secret", "CLICKHOUSE_HOST": "ch"}) == "client"
    assert (seen["host"], seen["username"], seen["password"], seen["autogenerate_session_id"]) == ("ch", "pack_admin", "secret", False)
