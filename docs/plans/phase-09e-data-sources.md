# Phase 9E: Data sources

## Goal

Connect a company's data wherever it lives (DECISIONS §4 Data sources) instead of loading one prepared dataset: a source manifest declares a PostgreSQL, MySQL/MariaDB, MongoDB or CSV/Parquet/S3 source and chooses per source whether ClickHouse copies it into `raw` on a schedule or reads it live through a database or table engine. dbt builds the marts over either, and the agent keeps writing ClickHouse SQL under the ClickHouse RBAC of DECISIONS §9.

## Scope

- Source manifest kinds and modes, extending the Phase 1 manifest contract in `jobs/sources/`.
- Read-only source credentials from `.env` through ClickHouse named collections.
- A sync job for copy mode and generated engine definitions for live mode.
- dbt staging over `raw` (copy) or `src_<source>` (live).
- The `sources` Compose profile with fixture PostgreSQL, MySQL, MongoDB and an S3-compatible store, seeded from one small synthetic dataset.
- Live tests that each kind and mode yields the same marts and that RBAC holds on live marts.

## Out of scope

- Generating MongoDB queries or any query language other than ClickHouse SQL.
- Writing to a source, change data capture and streaming ingestion.
- A scheduler service: copy-mode syncs run from the job, by hand, from CI or from the host's scheduler.
- Onboarding a second company (Phase 11), which uses this phase.

## Prerequisites

- Phases 1, 2 and 6: manifest loader, compiler, ClickHouse RBAC.
- Phase 9B: values from a new source are screened when the compiler indexes them.

## Deliverables

```text
jobs/sources/<pack>.yaml             # kind, mode, connection_env, tables or collections, columns for MongoDB
jobs/sync_sources.py                 # copy mode: INSERT INTO raw.* SELECT from the source, per table, idempotent
jobs/lib/source_manifest.py          # manifest model and validation
jobs/lib/source_engines.py           # live mode: CREATE DATABASE src_<source> / table engines from the manifest
infra/clickhouse/config.d/sources.xml # named collections with credentials from the environment
compose.yaml                         # sources profile: postgres, mysql, mongodb, s3 store, fixture seeding
infra/sources/fixtures/              # small synthetic dataset and seed scripts per kind
dbt/models/<pack>/staging/           # staging models selectable over raw or src_<source>
apps/api/tests/                      # live tests per kind and mode, RBAC on live marts
```

## Tasks

1. **Manifest contract (test first).** Extend the manifest with `kind` (`huggingface`, `postgres`, `mysql`, `mongodb`, `files`), `mode` (`copy`, default, or `live`), `connection_env` (the prefix of the `.env` variables holding host, port, database, user and password) and per-table source names; MongoDB tables list their columns and types; `files` lists paths or S3 URLs with their format. The existing `ecommerce_twin` manifest stays valid as `kind: huggingface`.
2. **Credentials.** A ClickHouse named collection per source reads its credentials from the environment, so engine definitions and sync queries never contain a password and `system.tables` shows none. Each source user is read-only on the source system; the fixtures create such users.
3. **Copy mode (test first).** `jobs/sync_sources.py --source <name>` copies each table into `raw.<pack>__<table>` through the named collection, replacing the previous copy atomically (load into a new table, then exchange), and records row counts against the manifest's expectations.
4. **Live mode (test first).** Generate `CREATE DATABASE src_<source> ENGINE = PostgreSQL|MySQL` or MongoDB/S3 table engines from the manifest; dbt marts over them are views. `src_*` databases are granted to no agent role, and the guard already blocks table functions.
5. **Fixtures.** One small synthetic dataset (a few tables, a few thousand rows, hand-generated, no licensed data) loaded into each fixture system by seed scripts in the `sources` profile.
6. **Equivalence (live test).** For each kind and supported mode, build the fixture marts and run the same set of SQL checks; results match the copy-mode marts exactly.
7. **RBAC on live marts (live test).** Column grants, row policies and aggregate-only views behave on marts built as views over live sources as they do on copied data; any gap is recorded and that mode is refused for policies that need it.
8. **Documentation.** `jobs/README.md` explains adding a source, choosing a mode and running syncs; `.env.example` lists the variables with placeholders only.

## Contracts

- Manifest fields of task 1, validated by JSON Schema like the other manifests.
- Raw table naming `raw.<pack>__<table>`; live databases `src_<source>`.
- Settings: `<PREFIX>_HOST`, `<PREFIX>_PORT`, `<PREFIX>_DATABASE`, `<PREFIX>_USER`, `<PREFIX>_PASSWORD` per source.

## Verification

```bash
uv run --project apps/api pytest -c apps/api/pyproject.toml
docker compose --profile sources config --quiet
docker compose --profile sources up --build --wait
docker compose run --rm api python -m jobs.sync_sources --source fixture_postgres
docker compose run --rm api python -m jobs.eval --pack ecommerce_twin --baseline packs/ecommerce_twin/eval_baseline.json
```

## Definition of done

| DoD item | Proof |
|---|---|
| Every kind and mode yields the same marts | Equivalence live test (task 6) |
| RBAC holds on live marts | RBAC live test (task 7) |
| No agent role reads `src_*` | Grant test |
| No credential appears in DDL, logs or `system.tables` | Test searching them for the fixture passwords |
| The first pack is unchanged | Pack eval against the baseline |

## Risks and open questions

1. **Row policies over external engines.** ClickHouse may not apply a row policy the same way on a view over a `PostgreSQL` database. Default: task 7 decides; a policy with a row filter forces copy mode for that dataset.
2. **Live query cost.** A live mart runs every question on the source. Default: copy is the default mode; live is documented for small, fresh-critical tables.
3. **MongoDB shape.** Nested documents do not map to columns. Default: flat collections only in live mode; others are copied and flattened in dbt.
4. **Type mapping.** Source types (numeric precision, time zones, enums) map differently per engine. Default: staging models cast explicitly, and the equivalence test catches drift.

## Web wiring

No feature is wired in this phase; the console's Datasets page shows marts as before.

## Branch and PR split

- `feat/db/declare-data-sources`: tasks 1-2 and 8.
- `feat/db/copy-sources-into-raw`: tasks 3 and 5.
- `feat/db/read-sources-live`: tasks 4, 6 and 7.
