# Phase 1: Data and marts

## Goal

Load the `ziadatalabs/FreeEcommerceTwin14M` dataset into the ClickHouse `raw` database and build the wide marts `sales_lines`, `returns_fact` and `sessions_daily` with dbt-clickhouse, so the acceptance question can be answered with hand-written SQL.

## Scope

- A generic, manifest-driven loader (`jobs/load_data.py`) and a refresh job (`jobs/refresh_data.py`) that runs the load and the dbt build for one source.
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
compose.yaml                        # jobs service (profile jobs) on the api image
jobs/
  load_data.py                      # loader: --source <name> [--revision <sha>]
  refresh_data.py                   # load + dbt build for one source
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
2. **Loader (test first).** Tests cover: manifest validation (missing table, bad row count type), download reuse of a complete file, refusal to publish a partial download, row-count mismatch failing the run, and a failure on the last table never being served as a complete load (open question 7). Then implement with `huggingface_hub` (pinned revision) and `clickhouse-connect` Arrow inserts. The loader knows nothing about e-commerce; everything comes from the manifest.
3. **dbt project.** Add `dbt-core` and `dbt-clickhouse` pinned in the jobs dependency group. `jobs/refresh_data.py` loads one source and runs `dbt build` for that source's models; any load, model or test failure fails the refresh, and a partial load or mart build is never served (open question 7). Staging models type dates as `Date`/`DateTime` in the pack timezone (open question 4) and money as `Decimal`.
4. **Marts.**
   - `sales_lines`: one row per order line: order line key, order id, order date and status, product attributes, customer attributes, quantity, unit price and line amount (the source has no order timestamp or discount). `MergeTree ORDER BY (order_date, product_id)`.
   - `returns_fact`: one row per returned line, joined to the original sale.
   - `sessions_daily`: one row per day x traffic dimensions with session and conversion counts.
5. **dbt tests.** `not_null` and `unique` on keys, `relationships` from marts to staging keys, accepted ranges for dates (2022-2026), non-negative quantities.
6. **Acceptance query.** `dbt/analyses/top_products_q1_compare.sql` ranks products by net sales in Q1 2025 and shows Q1 2024 alongside, with the difference and percentage computed in SQL. A test re-derives the same top 10 from the staging tables (an independent join path) and asserts equality.

## Contracts

- Source manifest keys: `name`, `hf_repo` (or another pinned download location), `revision`, `dbt_tag`, `tables[] {name, file, format, expected_rows, date_range?, card_rows?}`. The optional `date_range {column, start, end}` bounds a table to a half-open range at load time; when it is set, `card_rows` records the full dataset-card count and `expected_rows` the bounded count the load must match. `dbt_tag` is unique across all manifests, and a refresh selects `+tag:<dbt_tag>` so upstream staging models are rebuilt with their marts.
- Raw publication: the loader writes every table to `raw.<table>__loading`, checks every row count, and only then exchanges each loading table into `raw.<table>`. A failed table drops all loading tables and leaves the previous raw tables untouched.
- Refresh state: `data_meta.refresh_log (source, generation, state, ts)` with `state` in `started`, `completed`, `failed`. A refresh holds the lock table `data_meta.refresh_lock_<source>`, created without `IF NOT EXISTS` so a second concurrent refresh fails at once, and records `completed` only after the load and every dbt model and test succeed.
- Reader protocol: a reader reads the latest state for its source before and after an operation and discards the result unless both reads show the same `completed` generation. The shared reader helper is added in Phase 2 with the first reader (`compile_pack`).
- Mart isolation: all packs share one dbt project, so dbt rejects two models resolving to the same `marts` relation; models must not set `alias`.
- Mart column names become the vocabulary of `packs/ecommerce_twin/datasets.yaml` in Phase 2.
- Net sales definition (open question 1) becomes `metrics.yaml: net_sales.sql_expr`.

## Verification

Jobs run in a `jobs` Compose service under the `jobs` profile. It uses the `api` image with the `jobs` dependency group, mounts `./data` and carries the ClickHouse admin credentials, so the long-running `api` service never holds them.

```bash
docker compose run --rm jobs python -m jobs.refresh_data --source ecommerce_twin
docker compose run --rm jobs dbt compile --project-dir dbt --profiles-dir dbt --select top_products_q1_compare
uv run --project apps/api pytest -c apps/api/pyproject.toml
```

Passing: the refresh reports every table with matching row counts, `dbt build` has zero failing tests; the cross-check test passes.

## Definition of done

| DoD item | Proof |
|---|---|
| Raw row counts match the dataset card | Loader summary table in the PR, compared with the manifest |
| Hand-written top-10 Q1 2024 vs Q1 2025 SQL is correct | Analysis output plus the independent cross-check test |

## Dataset facts

Inspected at revision `d1bddd9a97a4fe31fd193e48c5826bbcd2b3022f`: seven Snappy Parquet files whose row counts equal the dataset card (14,328,942 rows in total). Every date column, `sessions.session_start` included, is a `YYYY-MM-DD` string; there are no timestamps. Money columns are 32-bit floats. There is no discount column: `line_total = quantity * unit_price` on every line. Order statuses are `delivered`, `cancelled`, `returned` and `shipped`. Primary keys are unique and every foreign key resolves.

## Risks and open questions

1. **Net sales definition.** Settled: the source has no discount, so net sales is `sum(line_amount)` over lines whose order is not `cancelled`; returns are not netted and `returns_fact` serves return metrics.
2. **Raw naming.** Settled: database `raw` as in DECISIONS §2, tables named after source tables (`raw.orders`).
3. **Where job code and tests live.** Settled: `jobs/` is a Python package in the api image; its tests live in `jobs/tests/` and run with the api project's pytest configuration.
4. **Timezone.** Settled: the source carries dates only, so staging types them as `Date` with no timezone conversion; the manifest records this. `sales_lines` has an order date and no order timestamp.
5. **Load size and time.** 14.3M rows is small for ClickHouse but download time depends on the network; the loader reuses completed downloads and never treats an incomplete one as complete.
6. **Licence.** CC BY-NC 4.0 forbids commercial use; the README states this and no derived data is committed.
7. **Refresh consistency.** Settled: refresh state and generation check, as defined under Contracts. A lock table rejects concurrent refreshes, readers verify one `completed` generation around each operation, dbt rejects colliding mart relations, `dbt_tag` values are unique and `+tag:` selection rebuilds upstream staging models.

## Branch and PR split

- `feat/db/load-ecommerce-twin-raw-data`: tasks 1-2.
- `feat/db/build-ecommerce-twin-marts`: tasks 3-6.
