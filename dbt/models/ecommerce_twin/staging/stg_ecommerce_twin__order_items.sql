select
    assumeNotNull(order_item_id) as order_item_id,
    assumeNotNull(order_id) as order_id,
    assumeNotNull(product_id) as product_id,
    assumeNotNull(quantity) as quantity,
    {{ to_money('unit_price') }} as unit_price,
    {{ to_money('line_total') }} as line_amount
from {{ source('ecommerce_twin', 'order_items') }}
