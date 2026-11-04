{{ config(engine='MergeTree()', order_by='(sold_on, sale_ref)') }}

select
    s.sale_id as sale_ref,
    s.sold_on as sold_on,
    w.widget_name as widget_name,
    w.widget_category as widget_category,
    s.region as region,
    s.quantity as widget_count,
    s.sale_amount as sale_amount
from {{ ref('stg_fixture_widgets__sales') }} as s
inner join {{ ref('stg_fixture_widgets__widgets') }} as w on w.widget_id = s.widget_id
