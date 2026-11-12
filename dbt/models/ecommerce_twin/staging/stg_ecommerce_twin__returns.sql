select
    assumeNotNull(return_id) as return_id,
    assumeNotNull(order_id) as order_id,
    assumeNotNull(order_item_id) as order_item_id,
    assumeNotNull(product_id) as product_id,
    toDate(assumeNotNull(return_date)) as return_date,
    assumeNotNull(reason) as reason,
    {{ to_money('refund_amount') }} as refund_amount
from {{ source('ecommerce_twin', 'returns') }}
