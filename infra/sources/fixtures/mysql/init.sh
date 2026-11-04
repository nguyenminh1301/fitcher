#!/bin/sh
# Seeds the fixture MySQL on a fresh volume: the widget tables from /fixtures,
# copied into the server's secure_file_priv directory, and a user that can only
# read them.
# The lab passwords are placed in SQL string literals, so they must not contain quotes.
set -eu

cp /fixtures/*.csv /var/lib/mysql-files/

mysql --protocol=socket -uroot -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE" <<SQL
CREATE TABLE widgets (
    widget_id varchar(8) PRIMARY KEY,
    widget_name varchar(64) NOT NULL,
    category varchar(16) NOT NULL,
    list_price decimal(10, 2) NOT NULL
);
CREATE TABLE sales (
    sale_id varchar(8) PRIMARY KEY,
    sold_on date NOT NULL,
    widget_id varchar(8) NOT NULL,
    region varchar(16) NOT NULL,
    quantity int NOT NULL,
    sale_amount decimal(12, 2) NOT NULL
);
CREATE TABLE refunds (
    refund_id varchar(8) PRIMARY KEY,
    sale_id varchar(8) NOT NULL,
    refunded_on date NOT NULL,
    refund_total decimal(12, 2) NOT NULL
);
LOAD DATA INFILE '/var/lib/mysql-files/widgets.csv' INTO TABLE widgets FIELDS TERMINATED BY ',' IGNORE 1 LINES;
LOAD DATA INFILE '/var/lib/mysql-files/sales.csv' INTO TABLE sales FIELDS TERMINATED BY ',' IGNORE 1 LINES;
LOAD DATA INFILE '/var/lib/mysql-files/refunds.csv' INTO TABLE refunds FIELDS TERMINATED BY ',' IGNORE 1 LINES;

CREATE USER '$FIXTURE_MYSQL_USER'@'%' IDENTIFIED BY '$FIXTURE_MYSQL_PASSWORD';
GRANT SELECT ON \`$MYSQL_DATABASE\`.* TO '$FIXTURE_MYSQL_USER'@'%';
SQL
