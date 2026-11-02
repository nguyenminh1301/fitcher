# Eval baseline: ecommerce_twin

Recorded on 2026-11-02 at the end of Phase 4 by running, against the compiled pack and the lab marts:

```bash
docker compose run --rm -v ./build/eval:/app/build/eval api python -m jobs.eval --pack ecommerce_twin --output-dir build/eval
```

The machine-readable copy is [packs/ecommerce_twin/eval_baseline.json](../../packs/ecommerce_twin/eval_baseline.json); later phases pass it as `--baseline` and must not regress (a layer regresses when its pass count over the cases both runs scored drops by more than one).
The execution match is below the 80% pack threshold. The failing cases come from these agent behaviors, seen in the SQL each case ran (`system.query_log`, `log_comment = eval-<case id>`):

- A filter value ("Electronics", "VIP", "mobile", "email") becomes a grouping column instead of a `WHERE` condition, so the answer has one row per value.
- "Top N" followed by a measure ("Top 5 brands by units sold") is refused because "Top" alone is treated as a vague ranking word.
- A two-period total ("orders in Q4 2025 compared with Q4 2024") is grouped by quarter, giving one row per period instead of one row with a column per period.
- "The same quarter last year" resolves to the wrong quarter.
- "Per month from January to June" is extracted as six monthly periods instead of one range broken down by month; the answer still matches.

Results vary between runs because the model's answers do; the regression tolerance of one case per layer absorbs that.

Reference date: 2026-01-15. Execution match 45% (10/22), threshold 80%: not met.

## Layers

| Layer | Passed | Failed | Not scored | Rate | Mean recall |
| --- | --- | --- | --- | --- | --- |
| intent | 0 | 0 | 31 | - | - |
| extraction | 14 | 8 | 9 | 64% | - |
| retrieval | 22 | 0 | 9 | 100% | 1.00 |
| execution | 10 | 12 | 9 | 45% | - |

## Categories

| Category | intent | extraction | retrieval | execution |
| --- | --- | --- | --- | --- |
| ambiguous | - | - | - | - |
| monthly_trend | - | 4/5 | 5/5 | 4/5 |
| out_of_scope | - | - | - | - |
| string_filter | - | 6/6 | 6/6 | 3/6 |
| top_n | - | 0/6 | 6/6 | 0/6 |
| two_period_compare | - | 4/5 | 5/5 | 3/5 |
| unauthorized | - | - | - | - |

## Cases

| Case | Category | intent | extraction | retrieval | execution | Reason |
| --- | --- | --- | --- | --- | --- | --- |
| top_products_q1_2024_vs_q1_2025 | two_period_compare | - | pass | pass | pass |  |
| top_brands_by_units_2025 | top_n | - | fail | pass | fail | rank_by: expected units_sold, got None |
| electronics_net_sales_west_2024 | string_filter | - | pass | pass | pass |  |
| monthly_conversion_rate_2025 | monthly_trend | - | pass | pass | pass |  |
| best_product_without_measure | ambiguous | - | - | - | - | not yet scored: active from phase 8 |
| marketing_asks_for_refunds | unauthorized | - | - | - | - | not yet scored: active from phase 6 |
| weather_question | out_of_scope | - | - | - | - | not yet scored: active from phase 8 |
| net_sales_by_region_2024_vs_2025 | two_period_compare | - | pass | pass | pass |  |
| orders_q4_2025_vs_q4_2024 | two_period_compare | - | pass | pass | fail | expected 1 rows, got 2 |
| conversion_rate_by_device_dec_2025_vs_dec_2024 | two_period_compare | - | pass | pass | pass |  |
| refunds_last_quarter_vs_same_quarter_last_year | two_period_compare | - | fail | pass | fail | periods: expected [('2024-10-01', '2025-01-01'), ('2025-10-01', '2026-01-01')], got [('2025-01-01', '2025-04-01'), ('2025-10-01', '2026-01-01')] |
| top_categories_by_net_sales_2025 | top_n | - | fail | pass | fail | rank_by: expected net_sales, got None |
| top_subcategories_by_units_last_month | top_n | - | fail | pass | fail | rank_by: expected units_sold, got None |
| top_channels_by_sessions_2025 | top_n | - | fail | pass | fail | rank_by: expected session_count, got None |
| top_return_reasons_by_refunds_2025 | top_n | - | fail | pass | fail | rank_by: expected refund_total, got None |
| top_customers_by_net_sales_q2_2025 | top_n | - | fail | pass | fail | rank_by: expected net_sales, got None |
| vip_net_sales_2025 | string_filter | - | pass | pass | fail | expected 1 rows, got 4 |
| paypal_orders_q3_2025 | string_filter | - | pass | pass | pass |  |
| mobile_sessions_last_month | string_filter | - | pass | pass | fail | expected 1 rows, got 3 |
| defective_returns_2025 | string_filter | - | pass | pass | pass |  |
| apparel_average_order_value_northeast_2024 | string_filter | - | pass | pass | fail | expected 1 rows, got 36 |
| monthly_orders_2024 | monthly_trend | - | pass | pass | pass |  |
| monthly_refunds_2025 | monthly_trend | - | pass | pass | pass |  |
| monthly_return_rate_jan_to_jun_2025 | monthly_trend | - | fail | pass | pass | periods: expected [('2025-01-01', '2025-07-01')], got [('2025-01-01', '2025-02-01'), ('2025-02-01', '2025-03-01'), ('2025-03-01', '2025-04-01'), ('2025-04-01', '2025-05-01'), ('2025-05-01', '2025-06-01'), ('2025-06-01', '2025-07-01')] |
| monthly_email_sessions_2025 | monthly_trend | - | pass | pass | fail | expected 12 rows, got 60 |
| performance_last_quarter_without_measure | ambiguous | - | - | - | - | not yet scored: active from phase 8 |
| best_region_last_year_without_measure | ambiguous | - | - | - | - | not yet scored: active from phase 8 |
| marketing_asks_for_net_sales_by_category | unauthorized | - | - | - | - | not yet scored: active from phase 6 |
| marketing_asks_for_top_customers | unauthorized | - | - | - | - | not yet scored: active from phase 6 |
| poem_request | out_of_scope | - | - | - | - | not yet scored: active from phase 8 |
| stock_price_question | out_of_scope | - | - | - | - | not yet scored: active from phase 8 |
