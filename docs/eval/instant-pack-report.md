# Instant packs against the hand-written packs

Phase 19 builds a pack from a connected source with no dbt model and no hand-written YAML ([plan](../plans/phase-19-instant-pack.md)).
This report measures how well such a pack answers, first for packs built by hand to the generator's rules (the baseline), later for the packs the generator itself produces.
The gap to the hand-written packs is part of the result and is stated, not hidden.

## How a generated pack is measured

The hand-written packs `ecommerce_twin` and `iowa_liquor` keep their eval sets.
A generated pack has other dataset, column and metric names and a single role, so it is measured on the hand-written pack's eval set:

```bash
docker compose run --rm -v ./build/eval:/app/build/eval api python -m jobs.eval --pack <generated> --cases-from <hand-written> --output-dir build/eval
```

The cases and their reference queries come from the hand-written pack; each reference runs as that pack's ClickHouse user of the case's role, and the agent answers from the generated pack as its only role.
Result sets are compared by value, never by name ([compare.py](../../apps/api/app/eval/compare.py)), so the execution layer is a fair comparison.
The retrieval layer is not: it checks the hand-written dataset and column names, which a generated pack never has, so it reads 0% and is left out below.
The three `unauthorized` cases cannot pass, because a generated pack has one role that reads every dataset.

## Baseline: built by hand to the generator's rules

Measured on 2026-11-14 with the same model tiers for all four runs (`fast` and `sql-small` on `openai/gpt-5.4-mini`, `sql-gen` on `openai/gpt-5.4`, `sql-gen-hard` on `openai/gpt-5.5`, `embed` on `openai/text-embedding-3-large`), reference date 2026-01-15.

### What was built

For each source, every table became a view `marts.<source>__<table>` with `SQL SECURITY DEFINER` over its copy in `raw`, keeping the column names:

- `iowa_liquor`: the one table `sales` of the PostgreSQL fixture, copied into `raw.iowa_liquor__sales` (2,490,620 rows).
- `ecommerce_twin`: the seven tables loaded from Hugging Face into `raw` (customers, products, sessions, orders, order_items, returns, support_tickets).

Two findings changed the rules before anything was measured:

- **Text columns must be typed.** Every Iowa column is text in the source, and every ecommerce date is a `YYYY-MM-DD` string; the dbt staging models typed them.
  Kept as text, no table has a time column, which every dataset needs, so neither pack could compile.
  The views therefore cast a text column whose non-empty values all parse as a date, a date and time or a number (a number with a leading zero stays text, because it is a code).
  Columns are still not renamed.
- **The wide view rule.** The plan's fact table (outgoing foreign keys, referenced by no selected table) leaves `order_items` without a wide view as soon as `returns` references it, and `order_items` has no date column of its own.
  The baseline gives every table with a single-column foreign key to another selected table a `__wide` view that joins each referenced table one level deep, its columns prefixed with that table's name.
  The Hugging Face tables declare no foreign keys; the baseline declares the ten the data implies (for example `order_items.order_id` to `orders`, `order_items.product_id` to `products`).

The pack files were then written deterministically: `datasets.yaml` from the views (numbers as measures, dates as time, other columns and keys as dimensions, string columns with at most 1,000 values indexable, wide views listed first), a `business_profile.yaml` with neutral defaults (`USD`, fiscal year from January, no conventions), one role reading every dataset, and the foreign keys as approved join paths.
`jobs.profile` and `jobs.draft_pack --allow-billable` filled the descriptions and drafted the glossary, metrics and examples from the profile alone; every drafted item was approved as drafted (none failed its test run), and the pack was compiled.

| Pack | Datasets | Join paths | Glossary terms | Metrics | Examples |
| --- | --- | --- | --- | --- | --- |
| Iowa, generated rules | 1 | 0 | 21 | 15 | 6 |
| Ecommerce, generated rules | 11 (5 wide; `order_items` alone has no time column and no dataset) | 7 | 25 | 28 | 10 |

The views read exactly the hand-written marts' data: the Iowa view and `marts.liquor_sales` both hold 2,490,620 rows, 30,441,277 bottles and USD 424,834,283.15 of sales.

### Result

| Layer | Iowa, hand-written | Iowa, generated rules | Ecommerce, hand-written | Ecommerce, generated rules |
| --- | --- | --- | --- | --- |
| Intent | 33/35 (94%) | 35/35 (100%) | 45/45 (100%) | 45/45 (100%) |
| Extraction | 22/24 (92%) | 16/24 (67%) | 25/28 (89%) | 21/28 (75%) |
| **Execution match** | **31/35 (89%)** | **16/35 (46%)** | **42/45 (93%)** | **24/45 (53%)** |

Execution match by category (generated rules against hand-written):

| Category | Iowa | Ecommerce |
| --- | --- | --- |
| two_period_compare | 2/4 against 4/4 | 1/5 against 4/5 |
| top_n | 1/5 against 5/5 | 3/6 against 6/6 |
| string_filter | 1/5 against 5/5 | 1/6 against 6/6 |
| monthly_trend | 2/4 against 3/4 | 3/5 against 5/5 |
| follow_up | 0/3 against 2/3 | 0/3 against 3/3 |
| definition | 4/4 against 4/4 | 8/8 against 8/8 |
| ambiguous | 3/3 against 2/3 | 3/3 against 2/3 |
| out_of_scope | 2/2 against 2/2 | 3/3 against 3/3 |
| chart_edit | 1/2 against 2/2 | 2/3 against 3/3 |
| unauthorized | 0/3 against 2/3 | 0/3 against 2/3 |

The gap is 43 points for Iowa and 40 points for ecommerce.

### Why the generated rules fail

The run status of each failed case, read from `agent_logs.runs`:

- **Iowa (19 failures): 12 clarifications.** Asked for "top 10 vendors by sales dollars", the agent asks which measure is meant: the drafted metrics overlap (gross sales dollars, estimated margin and several averages) and the neutral business profile has no convention saying what "sales" or "best-selling" means. The hand-written pack has one `best_selling` convention.
- **Ecommerce (21 failures): 8 rejected, 3 clarifications, 10 wrong answers.** The rejections pick the narrow `orders` mart for questions about products, categories or customers, then find no `category`, `region` or `Electronics` there: with twelve similar datasets, retrieval often prefers a base mart to the wide view that holds the column. Most wrong answers compute the measure on another dataset or grain than the hand-written metric: the drafted metrics exclude cancelled orders as the hand-written ones do, but there are several of them, for example net sales from the orders' `order_total` and from the order lines' `line_total`, and the agent often picks the orders one.
- **Both:** follow-ups fail where their first question already failed, and the three `unauthorized` cases cannot pass with a single role.

### What this decides

- The wide views are needed: without them no ecommerce dataset has products and order dates together, and every category, product and region question fails. The generator keeps the wider rule above.
- The text typing is needed for both sources.
- The largest remaining losses come from the business profile without conventions and from base marts that compete with their wide view. The generator therefore lists the wide view first and says in each base mart's description that the wide view holds its joined columns; conventions stay a Review task, as the plan's default for answer quality says.
- The generator passes when each generated pack reaches at least the baseline: **46% for Iowa and 53% for ecommerce**.
