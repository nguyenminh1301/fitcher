-- Money is converted from 32-bit floats; every line amount must still equal
-- quantity times unit price exactly after the conversion.
select order_item_id, quantity, unit_price, line_amount
from {{ ref('stg_ecommerce_twin__order_items') }}
where line_amount != quantity * unit_price
