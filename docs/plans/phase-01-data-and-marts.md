# Phase 1: Data and marts

## Goal

Load the `ziadatalabs/FreeEcommerceTwin14M` dataset into the ClickHouse `raw` database and build the wide marts `sales_lines`, `returns_fact` and `sessions_daily` with dbt-clickhouse, so the acceptance question can be answered with hand-written SQL.

## Scope

- A generic, manifest-driven loader (`jobs/load_data.py`) run inside one serialized refresh job (`jobs/refresh_data.py`) that also runs dbt.
- A dbt project with staging models, the three marts and their tests.
- A hand-written acceptance query with an independent cross-check.

## Out of scope

- Domain Pack files and OpenSearch (Phase 2).
- Agent code or any SQL generation (Phase 3).
- Per-role views and grants (Phase 6).

## Prerequisites

- Phase 0: healthy `clickhouse` with databases `raw` and `marts`, `api` image carrying `jobs/`.
- The dataset licence (CC BY-NC 4.0) is acknowledged in README; data stays in ignored `data/`.

## Deliverables

```text
jobs/
  load_data.py                      # loader: --source <name> [--revision <sha>]
  refresh_data.py                   # single-flight load + dbt build with refresh-state transitions
  sources/ecommerce_twin.yaml       # HF repo, pinned revision, files, target tables, expected rows
  lib/clickhouse.py                 # shared admin connection helper for jobs
dbt/
  dbt_project.yml
  profiles.yml                      # reads host/user/password from env
  models/ecommerce_twin/
    staging/stg_*.sql               # one per raw table: typing, renaming, dedup
    marts/sales_lines.sql
    marts/returns_fact.sql
    marts/sessions_daily.sql
    marts/schema.yml                # descriptions and tests
  analyses/top_products_q1_compare.sql
apps/api/tests/ or jobs/tests/      # loader tests (see open question 3)
```

## Tasks

1. **Inspect the dataset.** Record the pinned Hugging Face revision, file formats, column names/types and the dataset card row counts in `jobs/sources/ecommerce_twin.yaml`. This step decides the real column names used by the marts.
2. **Loader (test first).** Tests cover: manifest validation (missing table, bad row count type), download reuse of a complete file, refusal to publish a partial download, row-count mismatch failing the run, and a refresh-state gate: ClickHouse cannot swap several tables atomically, so consistency is enforced by state instead. `data_meta.refresh_state` is an append-only MergeTree table of transitions `(ts DateTime64(6), run_id UUID, status, detail)`, and each transition is one single-row insert. The current state is always read as one complete record: `SELECT status, run_id, ts FROM data_meta.refresh_state ORDER BY ts DESC, run_id DESC LIMIT 1`. The loader replaces each table through a temporary table and `EXCHANGE TABLES` and validates every table. Tests cover a failure on the last table and a failed state write. Then implement with `huggingface_hub` (pinned revision) and `clickhouse-connect` Arrow inserts. The loader knows nothing about e-commerce; everything comes from the manifest.
3. **dbt project.** Add `dbt-core` and `dbt-clickhouse` pinned in the jobs dependency group. `jobs/refresh_data.py` is the only writer of `raw`, `marts` and the refresh state. It first takes an exclusive `flock` on `refresh.lock` in a named volume shared by every `api`-image container, and fails fast if another refresh holds it, so loads and dbt runs never interleave. Holding the lock, it generates a `run_id` and appends `loading`, runs the loader, appends `loaded`, appends `building`, runs `dbt build`, then appends `ready` on success or `failed` on any load, model or test failure. Before each append it reads the latest transition and aborts unless that record carries its own `run_id` (or, for `loading`, a terminal state), so a stale run can never publish `ready` over another run. The `ready` gate applies to serving readers only: the agent, `compile_pack` and the onboarding profiler refuse with the latest state and run id unless it is `ready`, while dbt reads `raw` freely inside the refresh job that holds the lock. A partial load or mart build is therefore never served, and rerunning the refresh restores `ready`. Tests cover a dbt failure after a successful load, dbt reading `raw` while the state is `building` and a serving reader being refused at the same time, a second refresh failing while the lock is held, and a stale run whose `run_id` is no longer latest being unable to append `ready`. Staging models type dates as `Date`/`DateTime` in the pack timezone (open question 4) and money as `Decimal`.
4. **Marts.**
   - `sales_lines`: one row per order line: order line key, order id, order timestamp and date, product attributes, customer attributes, quantity, unit price, discount, gross and net line amounts. `MergeTree ORDER BY (order_date, product_id)`.
   - `returns_fact`: one row per returned line, joined to the original sale.
   - `sessions_daily`: one row per day x traffic dimensions with session and conversion counts.
5. **dbt tests.** `not_null` and `unique` on keys, `relationships` from marts to staging keys, accepted ranges for dates (2022-2026), non-negative quantities.
6. **Acceptance query.** `dbt/analyses/top_products_q1_compare.sql` ranks products by net sales in Q1 2025 and shows Q1 2024 alongside, with the difference and percentage computed in SQL. A test re-derives the same top 10 from the staging tables (an independent join path) and asserts equality.

## Contracts

- Source manifest keys: `name`, `hf_repo`, `revision`, `tables[] {name, file, format, expected_rows}`.
- Mart column names become the vocabulary of `packs/ecommerce_twin/datasets.yaml` in Phase 2.
- Net sales definition (open question 1) becomes `metrics.yaml: net_sales.sql_expr`.

## Verification

```bash
docker compose run --rm api python -m jobs.refresh_data --source ecommerce_twin
docker compose run --rm api dbt compile --project-dir dbt --profiles-dir dbt --select analyses/top_products_q1_compare
uv run --project apps/api pytest -c apps/api/pyproject.toml
```

Passing: the refresh reports every table with matching row counts, `dbt build` has zero failing tests and the latest refresh state is `ready`; the cross-check test passes.

## Definition of done

| DoD item | Proof |
|---|---|
| Raw row counts match the dataset card | Loader summary table in the PR, compared with the manifest |
| Hand-written top-10 Q1 2024 vs Q1 2025 SQL is correct | Analysis output plus the independent cross-check test |

## Risks and open questions

1. **Net sales definition.** Gross minus discounts, with or without returns? Default: `sum(quantity * unit_price - discount)` excluding cancelled orders, returns not netted; `returns_fact` serves return metrics.
2. **Raw naming.** DECISIONS §2 says database `raw`; §11 says `raw_*`. Default: database `raw` as in §2, tables named after source tables (`raw.orders`).
3. **Where job code and tests live.** Default: `jobs/` is a Python package installed in the api image; its tests live in `jobs/tests/` and run with the api project's pytest configuration.
4. **Timezone.** Timestamps in the source may be naive. Default: treat source timestamps as UTC and convert to the pack timezone in staging; record the assumption in the manifest.
5. **Load size and time.** 14.3M rows is small for ClickHouse but download time depends on the network; the loader must resume or reuse completed files.
6. **Licence.** CC BY-NC 4.0 forbids commercial use; the README states this and no derived data is committed.
7. **Refresh downtime.** The state gate makes the agent unavailable between `loading` and `ready`. Default: acceptable for a lab; refreshes are manual maintenance.

## Branch and PR split

- `feat/db/load-ecommerce-twin-raw-data`: tasks 1-2.
- `feat/db/build-ecommerce-twin-marts`: tasks 3-6.
