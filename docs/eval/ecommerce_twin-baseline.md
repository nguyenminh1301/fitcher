# Eval baseline: ecommerce_twin

Recorded on 2026-11-02 by running, against the compiled pack and the lab marts:

```bash
docker compose run --rm -v ./build/eval:/app/build/eval api python -m jobs.eval --pack ecommerce_twin --baseline packs/ecommerce_twin/eval_baseline.json --output-dir build/eval
```

The machine-readable copy is [packs/ecommerce_twin/eval_baseline.json](../../packs/ecommerce_twin/eval_baseline.json); later phases pass it as `--baseline` and must not regress (a layer regresses when its pass count over the cases both runs scored drops by more than one).

The first baseline, recorded at the end of Phase 4, matched 10 of 22 scored cases on execution. This one follows the fixes for "top N" questions that name their measure and the `extract.v2` prompt, and matches 20 of 22. The remaining differences, seen in the SQL each case ran (`system.query_log`, `log_comment = eval-<case id>`):

- "Customers" resolves to `customer_segment`: the pack has no glossary term mapping customers to `customer_id`, so the closest search hit wins.
- "The same quarter last year" still resolves to the wrong quarter.
- "Per month from January to June" is extracted as six monthly periods instead of one range broken down by month; the answer still matches.

Results vary between runs because the model's answers do; the regression tolerance of one case per layer absorbs that.

Reference date: 2026-01-15. Execution match 91% (20/22), threshold 80%: met.

## Layers

| Layer | Passed | Failed | Not scored | Rate | Mean recall |
| --- | --- | --- | --- | --- | --- |
| intent | 0 | 0 | 31 | - | - |
| extraction | 20 | 2 | 9 | 91% | - |
| retrieval | 22 | 0 | 9 | 100% | 1.00 |
| execution | 20 | 2 | 9 | 91% | - |

## Categories

| Category | intent | extraction | retrieval | execution |
| --- | --- | --- | --- | --- |
| ambiguous | - | - | - | - |
| monthly_trend | - | 4/5 | 5/5 | 5/5 |
| out_of_scope | - | - | - | - |
| string_filter | - | 6/6 | 6/6 | 6/6 |
| top_n | - | 6/6 | 6/6 | 5/6 |
| two_period_compare | - | 4/5 | 5/5 | 4/5 |
| unauthorized | - | - | - | - |

## Cases

| Case | Category | intent | extraction | retrieval | execution | Reason |
| --- | --- | --- | --- | --- | --- | --- |
| top_products_q1_2024_vs_q1_2025 | two_period_compare | - | pass | pass | pass |  |
| top_brands_by_units_2025 | top_n | - | pass | pass | pass |  |
| electronics_net_sales_west_2024 | string_filter | - | pass | pass | pass |  |
| monthly_conversion_rate_2025 | monthly_trend | - | pass | pass | pass |  |
| best_product_without_measure | ambiguous | - | - | - | - | not yet scored: active from phase 8 |
| marketing_asks_for_refunds | unauthorized | - | - | - | - | not yet scored: active from phase 6 |
| weather_question | out_of_scope | - | - | - | - | not yet scored: active from phase 8 |
| net_sales_by_region_2024_vs_2025 | two_period_compare | - | pass | pass | pass |  |
| orders_q4_2025_vs_q4_2024 | two_period_compare | - | pass | pass | pass |  |
| conversion_rate_by_device_dec_2025_vs_dec_2024 | two_period_compare | - | pass | pass | pass |  |
| refunds_last_quarter_vs_same_quarter_last_year | two_period_compare | - | fail | pass | fail | periods: expected [('2024-10-01', '2025-01-01'), ('2025-10-01', '2026-01-01')], got [('2025-01-01', '2025-04-01'), ('2025-10-01', '2026-01-01')] |
| top_categories_by_net_sales_2025 | top_n | - | pass | pass | pass |  |
| top_subcategories_by_units_last_month | top_n | - | pass | pass | pass |  |
| top_channels_by_sessions_2025 | top_n | - | pass | pass | pass |  |
| top_return_reasons_by_refunds_2025 | top_n | - | pass | pass | pass |  |
| top_customers_by_net_sales_q2_2025 | top_n | - | pass | pass | fail | expected 10 rows, got 4 |
| vip_net_sales_2025 | string_filter | - | pass | pass | pass |  |
| paypal_orders_q3_2025 | string_filter | - | pass | pass | pass |  |
| mobile_sessions_last_month | string_filter | - | pass | pass | pass |  |
| defective_returns_2025 | string_filter | - | pass | pass | pass |  |
| apparel_average_order_value_northeast_2024 | string_filter | - | pass | pass | pass |  |
| monthly_orders_2024 | monthly_trend | - | pass | pass | pass |  |
| monthly_refunds_2025 | monthly_trend | - | pass | pass | pass |  |
| monthly_return_rate_jan_to_jun_2025 | monthly_trend | - | fail | pass | pass | periods: expected [('2025-01-01', '2025-07-01')], got [('2025-01-01', '2025-02-01'), ('2025-02-01', '2025-03-01'), ('2025-03-01', '2025-04-01'), ('2025-04-01', '2025-05-01'), ('2025-05-01', '2025-06-01'), ('2025-06-01', '2025-07-01')] |
| monthly_email_sessions_2025 | monthly_trend | - | pass | pass | pass |  |
| performance_last_quarter_without_measure | ambiguous | - | - | - | - | not yet scored: active from phase 8 |
| best_region_last_year_without_measure | ambiguous | - | - | - | - | not yet scored: active from phase 8 |
| marketing_asks_for_net_sales_by_category | unauthorized | - | - | - | - | not yet scored: active from phase 6 |
| marketing_asks_for_top_customers | unauthorized | - | - | - | - | not yet scored: active from phase 6 |
| poem_request | out_of_scope | - | - | - | - | not yet scored: active from phase 8 |
| stock_price_question | out_of_scope | - | - | - | - | not yet scored: active from phase 8 |
