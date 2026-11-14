#!/bin/bash
# Seeds the fixture SQL Server: starts the server, creates the widget tables from /fixtures, a type probe table
# and a login that can only read them, then keeps the server in the foreground. The image's own entrypoint runs
# no init scripts, so this script is the container's command.
# The lab passwords are placed in SQL literals, so they must not contain quotes. FIXTURE_ADMIN_PASSWORD is the
# server's administrator (sa) and never leaves this container.
set -eu

/opt/mssql/bin/sqlservr &
server=$!
sqlcmd=/opt/mssql-tools18/bin/sqlcmd

for _ in $(seq 1 90); do
    if "$sqlcmd" -C -S localhost -U sa -P "$MSSQL_SA_PASSWORD" -Q "SELECT 1" >/dev/null 2>&1; then break; fi
    sleep 2
done

if ! "$sqlcmd" -C -S localhost -U sa -P "$MSSQL_SA_PASSWORD" -h -1 -Q "SET NOCOUNT ON; SELECT COUNT(*) FROM sys.databases WHERE name = '$FIXTURE_SQLSERVER_DATABASE'" | grep -q '^ *1'; then
    "$sqlcmd" -C -S localhost -U sa -P "$MSSQL_SA_PASSWORD" -b -Q "
CREATE DATABASE [$FIXTURE_SQLSERVER_DATABASE] COLLATE Vietnamese_100_CI_AS_SC_UTF8;
"
    "$sqlcmd" -C -S localhost -U sa -P "$MSSQL_SA_PASSWORD" -d "$FIXTURE_SQLSERVER_DATABASE" -b -Q "
CREATE TABLE dbo.widgets (
    widget_id varchar(8) NOT NULL PRIMARY KEY,
    widget_name nvarchar(64) NOT NULL,
    category varchar(16) NOT NULL,
    list_price decimal(10, 2) NOT NULL
);
CREATE TABLE dbo.sales (
    sale_id varchar(8) NOT NULL PRIMARY KEY,
    sold_on date NOT NULL,
    widget_id varchar(8) NOT NULL REFERENCES dbo.widgets (widget_id),
    region varchar(16) NOT NULL,
    quantity int NOT NULL,
    sale_amount decimal(12, 2) NOT NULL
);
CREATE INDEX sales_by_widget ON dbo.sales (widget_id);
CREATE TABLE dbo.refunds (
    refund_id varchar(8) NOT NULL PRIMARY KEY,
    sale_id varchar(8) NOT NULL REFERENCES dbo.sales (sale_id),
    refunded_on date NOT NULL,
    refund_total decimal(12, 2) NOT NULL
);
BULK INSERT dbo.widgets FROM '/fixtures/widgets.csv' WITH (FORMAT = 'CSV', FIRSTROW = 2, FIELDTERMINATOR = ',', ROWTERMINATOR = '0x0a');
BULK INSERT dbo.sales FROM '/fixtures/sales.csv' WITH (FORMAT = 'CSV', FIRSTROW = 2, FIELDTERMINATOR = ',', ROWTERMINATOR = '0x0a');
BULK INSERT dbo.refunds FROM '/fixtures/refunds.csv' WITH (FORMAT = 'CSV', FIRSTROW = 2, FIELDTERMINATOR = ',', ROWTERMINATOR = '0x0a');
CREATE TABLE dbo.type_probe (
    id int NOT NULL PRIMARY KEY,
    moment datetime2(6) NOT NULL,
    amount decimal(18, 4) NOT NULL,
    label nvarchar(100) NOT NULL,
    flag bit NOT NULL,
    token uniqueidentifier NOT NULL
);
INSERT INTO dbo.type_probe VALUES
    (1, '2025-03-04T05:06:07.123456', 12345.6789, N'Hà Nội — Đà Nẵng, Sài Gòn', 1, '6F9619FF-8B86-D011-B42D-00C04FC964FF'),
    (2, '2024-12-31T23:59:59.999999', -0.0001, N'Phở bò ăn liền', 0, '00000000-0000-0000-0000-000000000000');
CREATE LOGIN [$FIXTURE_SQLSERVER_USER] WITH PASSWORD = '$FIXTURE_SQLSERVER_PASSWORD', CHECK_POLICY = OFF;
CREATE USER [$FIXTURE_SQLSERVER_USER] FOR LOGIN [$FIXTURE_SQLSERVER_USER];
ALTER ROLE db_datareader ADD MEMBER [$FIXTURE_SQLSERVER_USER];
"
fi

touch /tmp/seeded
wait "$server"
