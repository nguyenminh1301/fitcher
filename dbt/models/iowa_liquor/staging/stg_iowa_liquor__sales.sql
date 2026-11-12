-- The export is text; numbers keep the source's sign (a negative line is a credit).
select
    toString(assumeNotNull(invoice_id)) as invoice_id,
    toDate(assumeNotNull(ordered_on)) as sale_date,
    trimBoth(toString(ifNull(store_no, ''))) as store_number,
    trimBoth(toString(ifNull(store_name, ''))) as store_name,
    upper(trimBoth(toString(ifNull(store_city, '')))) as store_city,
    trimBoth(toString(ifNull(store_zip_code, ''))) as store_zip_code,
    upper(trimBoth(toString(ifNull(county_name, '')))) as county_name,
    trimBoth(toString(ifNull(category_name, ''))) as category_name,
    trimBoth(toString(ifNull(vendor_name, ''))) as vendor_name,
    trimBoth(toString(ifNull(item_no, ''))) as item_number,
    trimBoth(toString(ifNull(im_desc, ''))) as item_description,
    toInt32OrZero(toString(ifNull(pack, ''))) as bottles_per_case,
    toInt32OrZero(toString(ifNull(bottle_volume_ml, ''))) as bottle_volume_ml,
    {{ to_money('toFloat64OrZero(toString(ifNull(state_bottle_cost, \'\')))') }} as state_bottle_cost,
    {{ to_money('toFloat64OrZero(toString(ifNull(state_bottle_retail, \'\')))') }} as state_bottle_retail,
    toInt32OrZero(toString(ifNull(sales_bottles, ''))) as bottles_sold,
    {{ to_money('toFloat64OrZero(toString(ifNull(sales_dollars, \'\')))') }} as sale_dollars,
    toFloat64OrZero(toString(ifNull(sales_liters, ''))) as liters_sold
from {{ source_table('sales') }}
