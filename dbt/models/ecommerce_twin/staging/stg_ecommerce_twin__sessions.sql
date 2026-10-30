-- session_start carries a date only in this source.
select
    assumeNotNull(session_id) as session_id,
    assumeNotNull(customer_id) as customer_id,
    toDate(assumeNotNull(session_start)) as session_date,
    assumeNotNull(device) as device,
    assumeNotNull(channel) as channel,
    assumeNotNull(pages_viewed) as pages_viewed,
    assumeNotNull(converted) as converted
from {{ source('ecommerce_twin', 'sessions') }}
