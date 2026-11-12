{{ config(engine='MergeTree()', order_by='(return_date, product_id)') }}

select
    r.return_id as return_id,
    r.return_date as return_date,
    r.reason as return_reason,
    r.refund_amount as refund_amount,
    s.order_item_id as order_item_id,
    s.order_id as order_id,
    s.order_date as order_date,
    s.order_status as order_status,
    s.product_id as product_id,
    s.product_category as product_category,
    s.product_subcategory as product_subcategory,
    s.product_brand as product_brand,
    s.customer_id as customer_id,
    s.customer_region as customer_region,
    s.customer_segment as customer_segment,
    s.quantity as quantity,
    s.line_amount as line_amount,
    dateDiff('day', s.order_date, r.return_date) as days_to_return
from {{ ref('stg_ecommerce_twin__returns') }} as r
inner join {{ ref('sales_lines') }} as s on s.order_item_id = r.order_item_id
