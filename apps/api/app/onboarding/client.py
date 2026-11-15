"""The ClickHouse connection that builds instant pack marts and applies pack policies: ``pack_admin``
(infra/clickhouse/users.d/pack_admin.xml)."""

from collections.abc import Mapping
import os

import clickhouse_connect

USER = "pack_admin"
PASSWORD_SETTING = "CLICKHOUSE_PACK_ADMIN_PASSWORD"
# Profiling and compiling a pack read whole marts; the client only waits for ClickHouse.
SEND_RECEIVE_TIMEOUT_SECONDS = 3600


def pack_admin_client(env: Mapping[str, str] | None = None):
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
        # Pipeline steps run on threads of the api; a session would serialize them.
        autogenerate_session_id=False,
    )
