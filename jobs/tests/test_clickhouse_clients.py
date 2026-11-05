import pytest

from jobs.lib import clickhouse


def test_sources_client_connects_as_source_loader(monkeypatch):
    seen = {}
    monkeypatch.setenv("CLICKHOUSE_SOURCES_PASSWORD", "secret")
    monkeypatch.setattr(clickhouse.clickhouse_connect, "get_client", lambda **kwargs: seen.update(kwargs))
    clickhouse.sources_client()
    assert (seen["username"], seen["password"]) == ("source_loader", "secret")


def test_sources_client_needs_its_password(monkeypatch):
    monkeypatch.delenv("CLICKHOUSE_SOURCES_PASSWORD", raising=False)
    with pytest.raises(RuntimeError, match="CLICKHOUSE_SOURCES_PASSWORD"):
        clickhouse.sources_client()
