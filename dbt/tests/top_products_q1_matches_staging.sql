-- Recomputes the acceptance answer (top 10 products by net sales in Q1 2025,
-- with Q1 2024 alongside) from the staging views instead of sales_lines and
-- returns every row where the two answers differ. Zero rows means they agree.
with expected as (
    select
        row_number() over (order by net_sales_q1_2025 desc, product_id) as sales_rank,
        product_id,
        net_sales_q1_2025,
        net_sales_q1_2024
    from (
        select
            p.product_id as product_id,
            sumIf(i.line_amount, o.order_date >= toDate('2025-01-01') and o.order_date < toDate('2025-04-01')) as net_sales_q1_2025,
            sumIf(i.line_amount, o.order_date >= toDate('2024-01-01') and o.order_date < toDate('2024-04-01')) as net_sales_q1_2024
        from {{ ref('stg_ecommerce_twin__order_items') }} as i
        inner join {{ ref('stg_ecommerce_twin__orders') }} as o on o.order_id = i.order_id
        inner join {{ ref('stg_ecommerce_twin__products') }} as p on p.product_id = i.product_id
        where o.order_status != 'cancelled'
        group by p.product_id
    )
    order by sales_rank
    limit 10
),

actual as (
    select sales_rank, product_id, net_sales_q1_2025, net_sales_q1_2024
    from ({{ top_products_q1_compare() }})
)

select 'missing from analysis' as problem, * from (select * from expected except select * from actual)
union all
select 'unexpected in analysis' as problem, * from (select * from actual except select * from expected)
union all
select 'analysis does not return 10 rows' as problem, toUInt64(count()), '', toDecimal128(0, 2), toDecimal128(0, 2)
from actual
having count() != 10
