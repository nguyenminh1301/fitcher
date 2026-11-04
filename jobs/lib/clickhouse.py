"""ClickHouse connections shared by jobs.

Only the ``jobs`` Compose service receives these credentials; the
long-running ``api`` service never does. ``source_loader`` is the only user
that may use the source named collections (DECISIONS §4 Data sources).
"""

import os

import clickhouse_connect

SOURCES_USER = "source_loader"


def admin_client():
    return _client(_required("CLICKHOUSE_ADMIN_USER"), _required("CLICKHOUSE_ADMIN_PASSWORD"))


def sources_client():
    return _client(SOURCES_USER, _required("CLICKHOUSE_SOURCES_PASSWORD"))


def _client(user: str, password: str):
    return clickhouse_connect.get_client(
        host=os.environ.get("CLICKHOUSE_HOST", "clickhouse"),
        port=int(os.environ.get("CLICKHOUSE_HTTP_PORT", "8123")),
        username=user,
        password=password,
    )


def _required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"{name} must be set")
    return value
