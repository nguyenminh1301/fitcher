#!/usr/bin/env bash
# Image smoke check of the release image's service users (docs/security.md, What the instance protects).
#
#   scripts/check_image_isolation.sh <image>
#
# Starts the image on a new volume, waits until it is healthy, then fails unless the web server runs as `web`,
# the api and ClickHouse as `app`, the `web` user can read neither the instance key, the secrets nor the rendered
# ClickHouse configuration, and the web server's environment holds no secret, not even a ClickHouse password
# supplied to the container. The container and volume are removed.
set -euo pipefail

image="${1:?usage: scripts/check_image_isolation.sh <image>}"
name="fitcher-isolation-$$"
volume="$name-data"
cleanup() {
    docker rm -f "$name" >/dev/null 2>&1 || true
    docker volume rm "$volume" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker run -d --name "$name" -v "$volume:/data" -e "CLICKHOUSE_AGENT_PASSWORD=isolation-check-$$" "$image" >/dev/null
for _ in $(seq 1 60); do
    status="$(docker inspect -f '{{.State.Health.Status}}' "$name")"
    [ "$status" = healthy ] && break
    sleep 3
done
if [ "$status" != healthy ]; then
    docker logs "$name" >&2 || true
    echo "the image did not become healthy" >&2
    exit 1
fi

failed=0
fail() {
    echo "FAIL: $*" >&2
    failed=1
}
uid_of() {
    docker exec "$name" sh -c "for p in /proc/[0-9]*; do awk '/^Name:/{n=\$2} /^Uid:/{if (n == \"$1\") print \$2}' \$p/status 2>/dev/null; done; true" | sort -u
}
[ "$(uid_of next-server)" = 10002 ] || fail "the web server does not run as uid 10002"
[ "$(uid_of uvicorn)" = 10001 ] || fail "the api does not run as uid 10001"
[ "$(uid_of clickhouse)" = 10001 ] || fail "ClickHouse does not run as uid 10001"
for path in /data/secret.key /data/secrets/api.env /data/secrets/admin.env /data/secrets/clickhouse.env \
    /data/app.db /run/fitcher/clickhouse/users.d/admin.xml; do
    if docker exec -u web "$name" cat "$path" >/dev/null 2>&1; then
        fail "the web user can read $path"
    fi
done
environment="$(docker exec -u web "$name" sh -c \
    'for p in /proc/[0-9]*; do grep -q "^Name:.next-server" $p/status 2>/dev/null && tr "\0" "\n" < $p/environ; done; true')"
[ -n "$environment" ] || fail "the web server's environment could not be read"
if printf '%s\n' "$environment" | grep -E '^(FITCHER_SECRET_KEY|CLICKHOUSE_[A-Z_]*PASSWORD)' >/dev/null; then
    fail "the web server's environment holds a secret"
fi
[ "$(docker exec "$name" fitcher migrate >/dev/null 2>&1; docker exec "$name" stat -c %u /data/app.db)" = 10001 ] \
    || fail "a job run with docker exec changed the owner of the app state"
[ "$failed" -eq 0 ] && echo "image isolation checks passed"
exit "$failed"
