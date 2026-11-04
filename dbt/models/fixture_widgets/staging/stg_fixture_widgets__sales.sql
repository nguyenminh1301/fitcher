-- Every source system types these columns differently, so staging casts each one.
select
    toString(assumeNotNull(sale_id)) as sale_id,
    toDate(assumeNotNull(sold_on)) as sold_on,
    toString(assumeNotNull(widget_id)) as widget_id,
    toString(assumeNotNull(region)) as region,
    toInt32(assumeNotNull(quantity)) as quantity,
    {{ to_money('sale_amount') }} as sale_amount
from {{ source_table('sales') }}
