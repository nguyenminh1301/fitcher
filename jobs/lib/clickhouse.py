"""ClickHouse admin connection shared by jobs.

Only the ``jobs`` Compose service receives the admin credentials; the
long-running ``api`` service never does.
"""

import os

import clickhouse_connect


def admin_client():
    user = _required("CLICKHOUSE_ADMIN_USER")
    password = _required("CLICKHOUSE_ADMIN_PASSWORD")
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
