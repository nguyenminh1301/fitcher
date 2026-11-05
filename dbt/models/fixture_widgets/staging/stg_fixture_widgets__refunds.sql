-- Every source system types these columns differently, so staging casts each one.
select
    toString(assumeNotNull(refund_id)) as refund_id,
    toString(assumeNotNull(sale_id)) as sale_id,
    toDate(assumeNotNull(refunded_on)) as refunded_on,
    {{ to_money('refund_total') }} as refund_total
from {{ source_table('refunds') }}
