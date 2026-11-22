#!/bin/sh
# Places the Free Synthetic E-commerce Twin (DECISIONS §4) in the fixture PostgreSQL with typed columns, primary
# keys and foreign keys, so the instant pack can be measured on a source that declares its joins
# (docs/eval/instant-pack-report.md). The rows are streamed from the ClickHouse copy that
# `jobs.refresh_data --source ecommerce_twin` loaded into raw; no password appears in a command line.
# Run from the repository root with the default stack and the `sources` profile up:
#   sh infra/sources/ecommerce_twin/seed.sh
# It recreates database ecommerce_twin each time. The read-only role of the Iowa fixture
# (IOWA_LIQUOR_POSTGRES_USER) may read it, so no new credential is needed.
set -eu
DIR=$(dirname "$0")
psql() {
    docker compose --profile sources exec -T postgres-fixture sh -c 'psql -v ON_ERROR_STOP=1 -q --username "${POSTGRES_USER:-postgres}" "$@"' psql "$@"
}

psql --dbname postgres -c "DROP DATABASE IF EXISTS ecommerce_twin WITH (FORCE)" -c "CREATE DATABASE ecommerce_twin"
psql --dbname ecommerce_twin < "$DIR/schema.sql"
for table in customers products sessions orders order_items returns support_tickets; do
    docker compose exec -T clickhouse sh -c \
        'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --query "SELECT * FROM raw.$0 FORMAT CSV"' "$table" \
        | psql --dbname ecommerce_twin -c "COPY $table FROM STDIN WITH (FORMAT csv, NULL '\\N')"
    echo "loaded $table"
done
psql --dbname ecommerce_twin < "$DIR/keys.sql"
docker compose --profile sources exec -T postgres-fixture sh -c \
    'psql -v ON_ERROR_STOP=1 -q --username "${POSTGRES_USER:-postgres}" --dbname ecommerce_twin \
       -c "GRANT CONNECT ON DATABASE ecommerce_twin TO \"$IOWA_LIQUOR_POSTGRES_USER\"" \
       -c "GRANT USAGE ON SCHEMA public TO \"$IOWA_LIQUOR_POSTGRES_USER\"" \
       -c "GRANT SELECT ON ALL TABLES IN SCHEMA public TO \"$IOWA_LIQUOR_POSTGRES_USER\""'
echo "ecommerce_twin is ready"
