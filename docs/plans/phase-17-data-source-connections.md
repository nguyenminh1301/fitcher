# Phase 17: Connect data sources in the application

## Goal

Let a user connect a PostgreSQL or MySQL/MariaDB database, or upload a CSV, Excel or Parquet file, from the interface: enter the connection, test it, choose tables and a mode per table, and keep copies fresh on a schedule. Credentials are stored only by ClickHouse (DECISIONS §4, §9, §15).

## Scope

- Source store, connection test, table listing with sizes and the proposed mode.
- Named collections created with SQL and stored encrypted by ClickHouse.
- Live attachment and copy, reusing the engine and sync code of the manifests.
- Scheduled and incremental copies.
- File upload as a copy-only source.
- Sources page and the setup's Data step.

## Out of scope

- SQL Server (Phase 18).
- Making a connected table answerable: marts and the pack come from Phase 19. After this phase a source is attached or copied and visible on the Sources page, and still needs a pack.
- MongoDB and S3 in the interface, SSH tunnels, change data capture.

## Prerequisites

- Phase 13 (app state), Phase 15 (who may manage sources). Phase 16 is not required.

## Deliverables

```text
apps/api/app/sources/store.py        # sources, tables and schedules in the app state (no credentials)
apps/api/app/sources/collections.py  # CREATE / ALTER / DROP NAMED COLLECTION through a dedicated ClickHouse user
apps/api/app/sources/inspect.py      # test a connection, list tables, sizes and keys through ClickHouse table functions
apps/api/app/sources/attach.py       # live databases and copies; shared with jobs.sync_sources
apps/api/app/sources/schedule.py     # due copies, one at a time per source
apps/api/app/sources/files.py        # upload, type check, load into raw
apps/api/app/api/sources.py          # source endpoints
infra/clickhouse/                    # encrypted named-collection storage and the source_admin user
apps/web/app/console/sources/        # Sources page
apps/web/app/setup/                  # Data step
```

## Tasks

1. **Named collections from SQL (test first, then live).** Configure ClickHouse to store SQL-created named collections encrypted, with the key derived from the instance secret. A `source_admin` user holds `named_collection_control` and may create engines on `src_*` and insert into `raw`; it cannot read collection secrets. The api writes a password once into the collection and keeps nothing. The XML collections of the fixture manifests keep working.
2. **Shared attach and copy code.** Move the engine definitions of `jobs/lib/source_engines.py` and the copy of `jobs/sync_sources.py` behind one module used by both the job and the api, without changing what the manifests do. The existing live suite must pass unchanged.
3. **Inspect (test first).** Test a connection and list schemas, tables, row estimates, on-disk sizes, primary keys and foreign keys by querying the source's catalog through `postgresql()` and `mysql()` with the named collection. No database driver is added to the api. A failed test returns one of a fixed set of reasons (unreachable, refused, authentication, TLS, database not found, permission), never the raw driver text.
4. **Source store and API (test first).** Endpoints of the Contracts section. Creating a source saves it only after a successful test. Editing a password replaces the collection. Deleting a source drops its `src_*` database, its `raw` tables and its collection after confirmation, and is refused while a pack uses its tables.
5. **Mode per table.** Propose live or copy by the rule of DECISIONS §14 from the sizes of task 3, and say why. A table read live through a view that joins other tables is flagged as slow.
6. **Scheduled copies (test first).** Each copied table has an interval (default daily) and optionally a cursor column. With a cursor, a sync inserts rows above the last value seen and records the new value; without one it reloads and swaps atomically as today. One sync runs per source at a time, a failed sync keeps the previous copy and records the error, and the Sources page shows the last result. The scheduler is a task of the api process; a second api process must not run the same sync, so the due check takes a row lock in the app state.
7. **Files (test first).** Upload CSV, XLSX or Parquet with a size cap; the type comes from the content; XLSX reuses the document parser's reader and rejects macro-enabled workbooks. Column types are inferred by ClickHouse from a sample and shown for confirmation before the load. The file is streamed into `raw` through the client so it works with an external ClickHouse; the original stays in the data directory for a reload.
8. **Sources page and Data step.** The form of DECISIONS §15 with per-kind fields and TLS options, the hint that a database on the Docker host is `host.docker.internal`, the test result, the table list with size, proposed mode and schedule, and each source's last sync. In team mode only an `admin` reaches it.
9. **Documentation.** README and `jobs/README.md` describe connecting a source in the interface and the read-only user to create on the source, with the exact grants for PostgreSQL and MySQL.

## Contracts

- `GET /sources`, `POST /sources/test`, `POST /sources`, `PATCH /sources/{id}`, `DELETE /sources/{id}`.
- `GET /sources/{id}/tables`, `PUT /sources/{id}/tables` (selection, mode, interval, cursor), `POST /sources/{id}/sync`, `GET /sources/{id}/syncs`.
- `POST /sources/files` (multipart), `POST /sources/files/{id}/load`.
- App state tables `sources`, `source_tables`, `source_syncs`. Naming is unchanged: `src_<source>` and `raw.<source>__<table>`.

## Verification

```bash
uv sync --project apps/api --frozen
uv run --project apps/api pytest -c apps/api/pyproject.toml
npm --prefix apps/web run typecheck && npm --prefix apps/web run test && npm --prefix apps/web run build
docker compose --profile sources up -d --build --wait
SOURCES_LIVE_TEST=1 uv run --project apps/api pytest -c apps/api/pyproject.toml -k sources
```

ClickHouse configuration changes are verified on a fresh volume and applied to an existing one through a schema change or a documented restart.

## Definition of done

- From the interface, the fixture PostgreSQL and MySQL are connected, their tables listed with sizes, one attached live and one copied; the next scheduled sync runs without a command.
- An incremental copy picks up rows added to the fixture and nothing else.
- No password is in `app.db`, in an API response, in `system.tables` or in the api log.
- A CSV and an XLSX upload become `raw` tables with the confirmed types.

## Risks and open questions

- Source catalogs report sizes differently and estimates can be stale. Default: use the catalog's estimate and label it as approximate.
- Type mapping of unusual columns (arrays, JSON, enums, geometry). Default: copy them as strings and mark them in the table list; do not fail the source.
- A long sync of a large table inside the api process. Default: it runs as a ClickHouse `INSERT ... SELECT`, so the api only waits; it is cancellable from the Sources page.

## Branch and PR split

`feat/db/store-source-credentials-in-clickhouse` (tasks 1 and 2), `feat/api/connect-sources-from-the-api` (3 to 5), `feat/db/copy-sources-on-a-schedule` (6), `feat/api/load-uploaded-files` (7), `feat/web/connect-sources-in-setup` (8 and 9).
