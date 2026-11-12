{# Acceptance question: the top 10 products by net sales in Q1 2025 with Q1
   2024 alongside, the difference and the percentage change, all computed in
   SQL. Net sales excludes cancelled orders; ties break on product_id. The
   percentage is NULL when a product had no Q1 2024 sales. Used by the analysis
   and by the cross-check test. #}
{% macro top_products_q1_compare() %}
select
    sales_rank,
    product_id,
    product_category,
    product_brand,
    net_sales_q1_2025,
    net_sales_q1_2024,
    net_sales_q1_2025 - net_sales_q1_2024 as net_sales_change,
    if(
        net_sales_q1_2024 = 0,
        NULL,
        round(100 * toFloat64(net_sales_q1_2025 - net_sales_q1_2024) / toFloat64(net_sales_q1_2024), 2)
    ) as net_sales_change_pct
from (
    select
        row_number() over (order by net_sales_q1_2025 desc, product_id) as sales_rank,
        *
    from (
        select
            product_id,
            any(product_category) as product_category,
            any(product_brand) as product_brand,
            sumIf(line_amount, order_date >= toDate('2025-01-01') and order_date < toDate('2025-04-01')) as net_sales_q1_2025,
            sumIf(line_amount, order_date >= toDate('2024-01-01') and order_date < toDate('2024-04-01')) as net_sales_q1_2024
        from {{ ref('sales_lines') }}
        where order_status != 'cancelled'
          and order_date >= toDate('2024-01-01')
          and order_date < toDate('2025-04-01')
        group by product_id
    )
)
order by sales_rank
limit 10
{% endmacro %}
