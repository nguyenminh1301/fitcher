select
    assumeNotNull(product_id) as product_id,
    assumeNotNull(category) as category,
    assumeNotNull(subcategory) as subcategory,
    assumeNotNull(brand) as brand,
    {{ to_money('price') }} as list_price,
    {{ to_money('cost') }} as unit_cost,
    toDate(assumeNotNull(launch_date)) as launch_date,
    round(toFloat64(assumeNotNull(avg_rating)), 1) as avg_rating
from {{ source('ecommerce_twin', 'products') }}
