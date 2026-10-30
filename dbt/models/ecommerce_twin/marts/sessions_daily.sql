{{ config(engine='MergeTree()', order_by='(session_date, device, channel, customer_region, customer_segment)') }}

select
    s.session_date as session_date,
    s.device as device,
    s.channel as channel,
    c.region as customer_region,
    c.segment as customer_segment,
    count() as sessions,
    countIf(s.converted) as converted_sessions,
    sum(s.pages_viewed) as pages_viewed
from {{ ref('stg_ecommerce_twin__sessions') }} as s
inner join {{ ref('stg_ecommerce_twin__customers') }} as c on c.customer_id = s.customer_id
group by session_date, device, channel, customer_region, customer_segment
