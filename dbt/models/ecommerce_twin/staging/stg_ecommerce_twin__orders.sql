select
    assumeNotNull(order_id) as order_id,
    assumeNotNull(customer_id) as customer_id,
    assumeNotNull(session_id) as session_id,
    toDate(assumeNotNull(order_date)) as order_date,
    assumeNotNull(status) as order_status,
    assumeNotNull(item_count) as item_count,
    {{ to_money('order_total') }} as order_total,
    assumeNotNull(payment_method) as payment_method
from {{ source('ecommerce_twin', 'orders') }}
