#!/bin/sh
# Seeds the fixture PostgreSQL on a fresh volume: the widget tables from
# /fixtures and a login role that can only read them.
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    -v reader="$FIXTURE_POSTGRES_USER" -v reader_password="$FIXTURE_POSTGRES_PASSWORD" <<'SQL'
CREATE TABLE widgets (
    widget_id text PRIMARY KEY,
    widget_name text NOT NULL,
    category text NOT NULL,
    list_price numeric(10, 2) NOT NULL
);
CREATE TABLE sales (
    sale_id text PRIMARY KEY,
    sold_on date NOT NULL,
    widget_id text NOT NULL REFERENCES widgets,
    region text NOT NULL,
    quantity integer NOT NULL,
    sale_amount numeric(12, 2) NOT NULL
);
CREATE TABLE refunds (
    refund_id text PRIMARY KEY,
    sale_id text NOT NULL REFERENCES sales,
    refunded_on date NOT NULL,
    refund_total numeric(12, 2) NOT NULL
);
COPY widgets FROM '/fixtures/widgets.csv' WITH (FORMAT csv, HEADER true);
COPY sales FROM '/fixtures/sales.csv' WITH (FORMAT csv, HEADER true);
COPY refunds FROM '/fixtures/refunds.csv' WITH (FORMAT csv, HEADER true);

CREATE ROLE :"reader" LOGIN PASSWORD :'reader_password';
ALTER ROLE :"reader" SET default_transaction_read_only = on;
GRANT USAGE ON SCHEMA public TO :"reader";
GRANT SELECT ON ALL TABLES IN SCHEMA public TO :"reader";
SQL
