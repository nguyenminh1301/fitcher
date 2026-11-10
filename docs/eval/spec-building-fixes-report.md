# Evals after the spec-building fixes

Measured on 2026-11-10 after three changes to how a question becomes a QuerySpec:

- glossary terms mapping "margin rate" to `average_state_margin_rate` (`iowa_liquor`) and "customer" to `customer_id` (`ecommerce_twin`);
- `build_spec` keeping a value named inside a metric term (for example "bourbon sales dollars") as a filter;
- an approved example may carry a reviewed `spec` that `build_spec` uses when the same question is asked again (DECISIONS §6 step 7), with the reviewed example `monthly_state_margin_rate` added to `packs/iowa_liquor/examples.yaml`.

Both packs were recompiled, then evaluated with:

```bash
docker compose run --rm -T -v ./build/eval:/app/build/eval api python -m jobs.eval --pack iowa_liquor --output-dir build/eval
docker compose run --rm -T -v ./build/eval:/app/build/eval api python -m jobs.eval --pack ecommerce_twin --baseline packs/ecommerce_twin/eval_baseline.json --output-dir build/eval
```

## Result

| Pack | Execution match | Before | Baseline regression |
| --- | --- | --- | --- |
| `iowa_liquor` | 30/35 (86%) | 29/35 ([report](iowa_liquor-report.md)) | no stored baseline |
| `ecommerce_twin` | 42/45 (93%) | 39/45 ([report](ecommerce_twin_regen-report.md)) | none |

All six ambiguous cases of both packs still ask a clarifying question.

## Cases that changed

| Pack | Case | Now | Cause |
| --- | --- | --- | --- |
| `iowa_liquor` | `monthly_margin_rate_2025` | pass | The reviewed example's spec was used; its question is the eval question word for word, so this shows the mechanism works, not that other phrasings resolve |
| `iowa_liquor` | `vodka_bottles_2025`, `vendor_partner_asks_for_margin` | pass | |
| `iowa_liquor` | `agave_tequila_liters_des_moines_2025` | fail | "Des Moines" resolved to `county_name` instead of `store_city` by value search ranking |
| `iowa_liquor` | `top_vendors_by_bottles_follow_up` | fail | The follow-up's extraction dropped the vendor dimension |
| `ecommerce_twin` | `top_customers_by_net_sales_q2_2025` | pass | "customers" now groups by `customer_id` |
| `ecommerce_twin` | `best_region_last_year_without_measure`, `monthly_orders_next_year_follow_up` | pass | |

The two new `iowa_liquor` failures come from value search and follow-up extraction, which these changes did not touch; model answers vary between runs.

## Still failing

| Pack | Case | Why |
| --- | --- | --- |
| `iowa_liquor` | `monthly_bourbon_sales_2025` | The extractor returned only "sales dollars" and no "bourbon", so no value term was left to turn into a filter |
| `iowa_liquor` | `average_without_measure` | "average" was extracted as the measure and answered instead of clarified |
| `iowa_liquor` | `top_counties_q4_follow_up` | The follow-up kept the whole year instead of Q4 |
| `ecommerce_twin` | `refunds_last_quarter_vs_same_quarter_last_year` | "The same quarter last year" resolves to the wrong quarter |
| `ecommerce_twin` | `marketing_asks_for_top_customers` | Clarified because the ranking phrase "mua nhiều nhất" has no convention, before the access check that the case expects to deny |
| `ecommerce_twin` | `net_sales_by_category_follow_up` | Follow-up extraction |
