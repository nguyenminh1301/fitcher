# Phase 18: SQL Server sources

## Goal

Connect a Microsoft SQL Server database like the other kinds. ClickHouse has no native SQL Server engine, so the source is reached through its ODBC bridge and FreeTDS; the phase starts by proving that this works inside the image and falls back to a copy-only path if it does not (DECISIONS §4).

## Scope

- A time-boxed proof with fixed pass criteria.
- The `sqlserver` source kind in the store, inspection, attach, copy and the Sources page.
- A development fixture.

## Out of scope

- Azure Active Directory and Kerberos authentication; SQL authentication only.
- Named instances resolved through SQL Browser; the form takes host and port.
- Other ODBC sources.

## Prerequisites

- Phase 17 (source connections). Phase 16 if the image must carry the ODBC libraries; before it, the development ClickHouse image is extended instead.

## Deliverables

```text
infra/clickhouse/odbc/               # FreeTDS and unixODBC configuration rendered per source
infra/sources/sqlserver/             # development fixture seeded with the widget dataset
apps/api/app/sources/                # sqlserver kind in inspect, attach and collections
docs/eval/sql-server-source-report.md # what the proof measured and the path chosen
```

## Tasks

1. **Proof (two days at most).** Extend the ClickHouse image with unixODBC, FreeTDS and `clickhouse-odbc-bridge`; start a SQL Server fixture in the `sources` profile; read a table through `odbc()` and through an `ODBC` table engine. Pass criteria, all required:
   - the fixture marts built live and by copy equal the copy-mode marts of the other kinds (the existing equivalence checks);
   - `datetime2`, `decimal`, `nvarchar` with Vietnamese text, `bit` and `uniqueidentifier` columns arrive with correct values;
   - a `WHERE` on an indexed column is sent to SQL Server (visible in the fixture's query log);
   - the connection uses TLS and its password is in no ClickHouse system table, log or process list;
   - a copy of one million rows finishes and the bridge process exits when idle.
2. **Record the result.** Write `docs/eval/sql-server-source-report.md` with each criterion's outcome and choose the path: the bridge (tasks 3 to 5) or the fallback (task 6). Update DECISIONS §4 if the fallback is taken.
3. **Bridge path: credentials.** ODBC data sources are files, not named collections. Render one data source per SQL Server source from the app state, with the password taken from an encrypted named collection or a file readable only by the ClickHouse user; state plainly in `infra/README.md` where the password lives.
4. **Bridge path: kind (test first).** Add `sqlserver` to inspection (catalog queries against `INFORMATION_SCHEMA` and `sys` views), attach (one `ODBC` table per selected table in `src_<source>`), copy and schedule. Schema is a connection field with `dbo` as the default.
5. **Sources page.** Fields: host, port, database, schema, user, password, encryption (required by default), trust server certificate (off by default, with a warning when turned on).
6. **Fallback: copy only.** If the proof fails, read SQL Server from the api with a pure FreeTDS-based Python driver and stream rows into `raw` in batches; the kind offers copy mode only and the Sources page says so. The password is then a Phase 13 secret, which DECISIONS §4 must record as the one exception to credentials living in ClickHouse.
7. **Supervision.** In the single image the bridge is started by ClickHouse on demand; confirm it runs as the application user and that the healthcheck is unaffected.

## Contracts

- Source kind `sqlserver`; connection fields of task 5.
- The fixture image needs the vendor's licence acceptance variable and is used in development only; it is never part of the release image.

## Verification

```bash
docker compose --profile sources up -d --build --wait
SOURCES_LIVE_TEST=1 uv run --project apps/api pytest -c apps/api/pyproject.toml -k "sources and sqlserver"
uv run --project apps/api pytest -c apps/api/pyproject.toml
npm --prefix apps/web run typecheck && npm --prefix apps/web run test
```

## Definition of done

- The report states which path was taken and why, with the measured criteria.
- From the interface, the SQL Server fixture is connected, its tables are listed and a table is copied; on the bridge path one is also read live.
- No SQL Server password is readable outside the place the report names.

## Risks and open questions

- The fixture image is published for `amd64` only and needs about 2 GB of memory. Default: skip its live tests on other architectures and say so in the test output.
- FreeTDS and newer SQL Server TLS defaults. Default: pin a FreeTDS version that negotiates TDS 7.4 with encryption and record it in the report.
- Licence of the vendor's own ODBC driver. Default: do not ship it; FreeTDS is LGPL.

## Branch and PR split

`feat/db/prove-sql-server-through-odbc` (tasks 1 and 2), then `feat/db/connect-sql-server-sources` (the chosen path) and `feat/web/add-sql-server-source-form`.
