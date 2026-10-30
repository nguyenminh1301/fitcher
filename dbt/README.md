# dbt project

dbt-clickhouse models transform the ClickHouse `raw` database into the wide marts the agent queries.
The agent never queries `raw` directly.

## Layout

| Path | Contents |
| --- | --- |
| `models/<source>/staging/` | `_sources.yml` for the raw tables and one `stg_<source>__<table>` view per table, materialized in `raw` |
| `models/<source>/marts/` | MergeTree tables materialized in `marts`, with descriptions and tests in `schema.yml` |
| `macros/` | `generate_schema_name` (models land in `raw` or `marts` verbatim), `to_money` and the acceptance query |
| `tests/` | local generic tests (`value_between`, `unique_combination`) and singular tests |
| `analyses/` | hand-written analysis SQL, compiled but never materialized |

Each source folder is tagged with its manifest's `dbt_tag` in `dbt_project.yml`, so `dbt build --select +tag:<dbt_tag>` rebuilds that source's staging views and marts only.
All sources share this project, so dbt rejects two models that resolve to the same relation; models never set `alias`.
No dbt packages are used, so builds need no network access.

## E-commerce lab marts

| Mart | Grain |
| --- | --- |
| `sales_lines` | one row per order line, with order, product and customer attributes |
| `returns_fact` | one row per returned line, joined to the original sale |
| `sessions_daily` | one row per day, device, channel, customer region and customer segment |

Staging types the source's `YYYY-MM-DD` strings as `Date` without timezone conversion and converts float money to `Decimal(18, 2)` through integer cents.
Net sales is `sum(line_amount)` over lines whose `order_status` is not `cancelled`; returns are not netted.

## Commands

Builds normally run through the refresh job, which also loads the raw tables and records the refresh state:

```bash
docker compose run --rm jobs python -m jobs.refresh_data --source ecommerce_twin
```

To build or compile by hand inside the `jobs` service:

```bash
docker compose run --rm jobs dbt build --project-dir dbt --profiles-dir dbt --select +tag:ecommerce_twin
docker compose run --rm jobs dbt compile --project-dir dbt --profiles-dir dbt --select top_products_q1_compare
```

The compiled acceptance query is written to `/tmp/dbt/target/compiled/fitcher/analyses/top_products_q1_compare.sql` inside the container.
The `top_products_q1_matches_staging` test recomputes the same answer from the staging views on every build.

See [DECISIONS §4](../docs/DECISIONS.md#4-lab-dataset) and the [Phase 1 plan](../docs/plans/phase-01-data-and-marts.md).
