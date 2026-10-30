{{ config(engine='MergeTree()', order_by='(order_date, product_id)') }}

select
    i.order_item_id as order_item_id,
    i.order_id as order_id,
    o.order_date as order_date,
    o.order_status as order_status,
    o.payment_method as payment_method,
    o.customer_id as customer_id,
    c.region as customer_region,
    c.segment as customer_segment,
    c.signup_date as customer_signup_date,
    i.product_id as product_id,
    p.category as product_category,
    p.subcategory as product_subcategory,
    p.brand as product_brand,
    p.list_price as product_list_price,
    p.unit_cost as product_unit_cost,
    i.quantity as quantity,
    i.unit_price as unit_price,
    i.line_amount as line_amount,
    i.order_item_id in (select order_item_id from {{ ref('stg_ecommerce_twin__returns') }}) as is_returned
from {{ ref('stg_ecommerce_twin__order_items') }} as i
inner join {{ ref('stg_ecommerce_twin__orders') }} as o on o.order_id = i.order_id
inner join {{ ref('stg_ecommerce_twin__products') }} as p on p.product_id = i.product_id
inner join {{ ref('stg_ecommerce_twin__customers') }} as c on c.customer_id = o.customer_id
