{{ config(engine='MergeTree()', order_by='(refunded_on, refund_ref)') }}

select
    r.refund_id as refund_ref,
    r.refunded_on as refunded_on,
    r.sale_id as sale_ref,
    w.widget_name as widget_name,
    r.refund_total as refund_total
from {{ ref('stg_fixture_widgets__refunds') }} as r
inner join {{ ref('stg_fixture_widgets__sales') }} as s on s.sale_id = r.sale_id
inner join {{ ref('stg_fixture_widgets__widgets') }} as w on w.widget_id = s.widget_id
