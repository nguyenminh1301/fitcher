#!/bin/sh
# Image healthcheck: healthy only when web, api and ClickHouse all answer, so a question could be answered.
set -a
. /data/secrets/api.env 2>/dev/null || exit 1
set +a
exec python - <<'PY'
import os, sys, urllib.request

checks = {
    "web": "http://127.0.0.1:3000/",
    "api": "http://127.0.0.1:8000/health",
    "clickhouse": f"http://{os.environ['CLICKHOUSE_HOST']}:{os.environ['CLICKHOUSE_HTTP_PORT']}/ping",
}
for name, url in checks.items():
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            if response.status >= 400:
                raise OSError(f"status {response.status}")
    except Exception as error:
        print(f"{name} does not answer: {error}", file=sys.stderr)
        sys.exit(1)
PY
