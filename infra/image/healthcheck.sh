#!/bin/sh
# Image healthcheck: healthy only when web, api and ClickHouse all answer, so a question could be answered.
set -a
. /data/secrets/api.env 2>/dev/null || exit 1
set +a
# http.client, not urllib: urllib asks for `Connection: close`, which the web server reads as a reverse proxy.
exec python - <<'PY'
import http.client, os, sys

checks = {
    "web": ("127.0.0.1", 3000, "/"),
    "api": ("127.0.0.1", 8000, "/health"),
    "clickhouse": (os.environ["CLICKHOUSE_HOST"], int(os.environ["CLICKHOUSE_HTTP_PORT"]), "/ping"),
}
for name, (host, port, path) in checks.items():
    connection = http.client.HTTPConnection(host, port, timeout=3)
    try:
        connection.request("GET", path)
        status = connection.getresponse().status
        if status >= 400:
            raise OSError(f"status {status}")
    except Exception as error:
        print(f"{name} does not answer: {error}", file=sys.stderr)
        sys.exit(1)
PY
