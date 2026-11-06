#!/bin/sh
# Places Iowa Liquor Sales 2025 in the fixture PostgreSQL as a company's own
# database would hold it: database iowa_liquor, one table sales with the
# export's columns as text (the dbt staging model types them), and a login role
# that may only read it. Run after infra/sources/iowa_liquor/fetch.py with
#   docker compose --profile sources exec postgres-fixture sh /seed/iowa_liquor/seed.sh
# It recreates the database each time, so running it again reloads the data.
set -eu

: "${IOWA_LIQUOR_POSTGRES_USER:?set IOWA_LIQUOR_POSTGRES_USER}"
: "${IOWA_LIQUOR_POSTGRES_PASSWORD:?set IOWA_LIQUOR_POSTGRES_PASSWORD}"
CSV=/sources/iowa_liquor/sales_2025.csv
[ -f "$CSV" ] || { echo "$CSV is missing; run infra/sources/iowa_liquor/fetch.py first" >&2; exit 1; }

psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER:-postgres}" --dbname postgres \
    -v reader="$IOWA_LIQUOR_POSTGRES_USER" -v reader_password="$IOWA_LIQUOR_POSTGRES_PASSWORD" <<'SQL'
DROP DATABASE IF EXISTS iowa_liquor WITH (FORCE);
CREATE DATABASE iowa_liquor;
SELECT format('CREATE ROLE %I LOGIN', :'reader')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'reader') \gexec
ALTER ROLE :"reader" WITH LOGIN PASSWORD :'reader_password';
ALTER ROLE :"reader" SET default_transaction_read_only = on;
SQL

psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER:-postgres}" --dbname iowa_liquor \
    -v reader="$IOWA_LIQUOR_POSTGRES_USER" <<'SQL'
CREATE TABLE sales (
    invoice_id text NOT NULL,
    ordered_on text,
    store_no text,
    store_name text,
    store_address text,
    store_city text,
    store_zip_code text,
    county_fips_code text,
    county_name text,
    category_code text,
    category_name text,
    vendor_number text,
    vendor_name text,
    item_no text,
    im_desc text,
    pack text,
    bottle_volume_ml text,
    state_bottle_cost text,
    state_bottle_retail text,
    sales_bottles text,
    sales_dollars text,
    sales_liters text,
    sales_gallons text
);
COPY sales FROM '/sources/iowa_liquor/sales_2025.csv' WITH (FORMAT csv, HEADER true);
REVOKE ALL ON DATABASE iowa_liquor FROM PUBLIC;
GRANT CONNECT ON DATABASE iowa_liquor TO :"reader";
GRANT USAGE ON SCHEMA public TO :"reader";
GRANT SELECT ON sales TO :"reader";
SELECT count(*) AS rows_loaded FROM sales;
SQL
