# SQL Server source: the ODBC bridge proof and the path chosen

Phase 18 of the [master plan](../MASTER_PLAN.md) connects Microsoft SQL Server like the other kinds. ClickHouse has no SQL Server engine, so the plan asked for a proof that its `odbc()` function and `ODBC` table engine work in the image through `clickhouse-odbc-bridge` and FreeTDS, with a copy-only fallback if they do not. This report records what was measured and the path taken: **the fallback**.

## Result in one paragraph

The ClickHouse 26.8 packages do not contain `clickhouse-odbc-bridge`, so the bridge path fails before its first criterion can be measured. SQL Server is therefore a copy-only source: the api reads it with `pymssql` (FreeTDS 1.5.19 bundled in the wheel, TDS 7.4, encryption required) and streams the rows into `raw` in batches of 20,000. All checks the plan lists for the proof were run against the fallback instead and pass, with two limits: the driver does not verify the server's certificate, and a login to a database that does not exist is reported like a wrong password.

## The proof of the bridge path

Environment: `clickhouse/clickhouse-server:26.8.36.3` (Ubuntu 22.04), the SQL Server 2022 fixture of the `sources` profile, on an amd64 host.

| Step | Outcome |
| --- | --- |
| Install unixODBC and FreeTDS in the image | Works: `apt-get install unixodbc tdsodbc` adds `libtdsodbc.so`. |
| Find `clickhouse-odbc-bridge` | **Not present.** `/usr/bin` of the official image holds only the `clickhouse` binary and its symlinks, and `clickhouse` has no `odbc-bridge` mode. `clickhouse-common-static-26.8.36.3-amd64.tgz` from packages.clickhouse.com holds `clickhouse` and `clickhouse-extract-from-config` only, and the recent GitHub release assets (26.3, 26.8 and 26.10 lines) list no bridge. The last package line that shipped it is 23.8. |
| Call `odbc()` in the stock server | The server starts `clickhouse-odbc-bridge` and the child exits with code 88: `Code: 302 CHILD_WAS_NOT_EXITED_NORMALLY`. |

Not done, on purpose: the 23.8 bridge binary was downloaded and not run. It is three years older than the server, unmaintained, and executing a binary from outside the pinned image would add an unreviewed component to a product whose image is scanned and pinned.

Because the bridge is absent, none of the five pass criteria of the bridge path could be met: marts built live and by copy over ODBC, exact types, a `WHERE` sent to SQL Server, TLS with no password in a ClickHouse table, log or process list, and a one million row copy with the bridge exiting when idle. The same intentions were checked on the fallback below.

## The fallback, measured

`apps/api/tests/test_sources_sqlserver_live.py` (`SOURCES_LIVE_TEST=1`, fixture up, 9 tests) on the fixture: 3,000 sales, 300 refunds, 40 widgets, a type probe table and a generated table of one million rows.

| Check | Result |
| --- | --- |
| Tables listed with estimate, size, primary and foreign keys | `sales`: 3,000 rows, primary key `sale_id`, foreign key to `widgets`. |
| Copy equals the copy of the same dataset from the fixture PostgreSQL | Row counts, sums, date bounds and a hash of every row of `sales`, `refunds` and `widgets` are equal. |
| `datetime2(6)`, `decimal(18,4)`, Vietnamese `nvarchar`, `bit`, `uniqueidentifier` | Arrive exactly as `DateTime64(6, 'UTC')`, `Decimal(18, 4)`, `String` (`Hà Nội — Đà Nẵng, Sài Gòn`), `Bool` and `UUID`. A naive `datetime2` is stored as its wall-clock value: an earlier run shifted every value by the api's own UTC offset until the columns were declared `UTC` and the values marked so. |
| Filter on an indexed column reaches SQL Server | An incremental copy sends `WHERE [id] > %s` in the query itself, so SQL Server filters and the api reads only the new rows; there is no engine in between that could decline to push it down. |
| TLS | `encryption=require` shows `encrypt_option = TRUE` in `sys.dm_exec_connections`; `prefer` negotiates when the server agrees. The server certificate is **not verified**: with a CA bundle configured FreeTDS still accepted the fixture's self-signed certificate. The form says so and offers no verify mode. |
| Password | A secret of the app state (`source:<id>:password`, AES-256-GCM under the instance key); absent from the state file's bytes, from `system.tables`, `system.query_log` and the named collections, and never created as a ClickHouse object. The exception to "credentials live in ClickHouse" is recorded in DECISIONS §4 and §9. |
| One million rows | Copied in 11.5 s; the api process grew by 28 MiB at most, because rows are fetched and inserted 20,000 at a time. |
| Incremental copy | Adds exactly the rows above the cursor (2 of 5) and not a row changed in place. |
| Failures | `unreachable`, `refused` and `authentication` are told apart. A login to a database that does not exist is reported by FreeTDS as `Login failed` (and on repeated attempts without any message), so it shows as `authentication`; `database_not_found` is not available for SQL Server. |

## Choices and limits

- Driver: `pymssql` 2.4.6, whose Linux wheels for amd64 and arm64 bundle FreeTDS (LGPL); Microsoft's own ODBC driver is not shipped. The pure Python alternative `python-tds` was rejected: it does not encrypt the data by default and enables TLS only with a CA file and `pyOpenSSL`.
- Authentication: SQL authentication only; the form takes host and port, so named instances behind SQL Browser are out of scope.
- Types without a ClickHouse counterpart (`xml`, `geography`, `geometry`, `hierarchyid`, `sql_variant`, binary types, `time`) are copied as text (binary as hex) and marked in the table list.
- The fixture image is amd64 only and needs about 2 GB of memory; its tests skip on other architectures and it is never part of the release image. Accepting Microsoft's licence terms (`ACCEPT_EULA`) is part of starting it.
- Supervision (plan task 7) does not apply: no bridge process exists, the api is the only process that talks to SQL Server, and the healthcheck is unchanged.

## Reproduce

```bash
docker compose --profile sources up -d --build --wait
SOURCES_LIVE_TEST=1 uv run --project apps/api pytest -c apps/api/pyproject.toml -k "sources and sqlserver"
```

When the test process cannot resolve the fixture's Compose name, set `SQLSERVER_LIVE_HOST` to the address it can reach.
