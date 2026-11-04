-- Every source system types these columns differently, so staging casts each one.
select
    toString(assumeNotNull(widget_id)) as widget_id,
    toString(assumeNotNull(widget_name)) as widget_name,
    toString(assumeNotNull(category)) as widget_category,
    {{ to_money('list_price') }} as list_price
from {{ source_table('widgets') }}
