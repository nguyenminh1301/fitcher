select
    assumeNotNull(customer_id) as customer_id,
    toDate(assumeNotNull(signup_date)) as signup_date,
    assumeNotNull(region) as region,
    assumeNotNull(segment) as segment,
    assumeNotNull(lifetime_orders) as lifetime_orders,
    {{ to_money('lifetime_spend') }} as lifetime_spend,
    assumeNotNull(email_domain) as email_domain
from {{ source('ecommerce_twin', 'customers') }}
