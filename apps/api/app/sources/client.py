"""The ClickHouse connection of the Sources page: ``source_admin`` (infra/clickhouse/users.d/source_admin.xml)."""

from collections.abc import Mapping
import os

import clickhouse_connect

USER = "source_admin"
PASSWORD_SETTING = "CLICKHOUSE_SOURCE_ADMIN_PASSWORD"
# A copy of a large table is one long INSERT ... SELECT inside ClickHouse; the client only waits for it.
SEND_RECEIVE_TIMEOUT_SECONDS = 6 * 3600


def source_admin_client(env: Mapping[str, str] | None = None):
    env = os.environ if env is None else env
    password = env.get(PASSWORD_SETTING, "")
    if not password:
        raise RuntimeError(f"{PASSWORD_SETTING} must be set")
    return clickhouse_connect.get_client(
        host=env.get("CLICKHOUSE_HOST", "clickhouse"),
        port=int(env.get("CLICKHOUSE_HTTP_PORT", "8123")),
        username=USER,
        password=password,
        connect_timeout=10,
        send_receive_timeout=SEND_RECEIVE_TIMEOUT_SECONDS,
        # Shared by the api's threads and its scheduler: a session would serialize them and refuse overlaps.
        autogenerate_session_id=False,
    )
