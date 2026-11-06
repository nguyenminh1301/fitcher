{{ config(engine='MergeTree()', order_by='(sale_date, store_number, item_number)') }}

-- One row per invoice line: a licensed store's purchase of one item from the state.
select
    invoice_id,
    sale_date,
    store_number,
    store_name,
    store_city,
    store_zip_code,
    county_name,
    category_name,
    vendor_name,
    item_number,
    item_description,
    bottles_per_case,
    bottle_volume_ml,
    state_bottle_cost,
    state_bottle_retail,
    bottles_sold,
    sale_dollars,
    liters_sold,
    (state_bottle_retail - state_bottle_cost) * bottles_sold as state_margin
from {{ ref('stg_iowa_liquor__sales') }}
