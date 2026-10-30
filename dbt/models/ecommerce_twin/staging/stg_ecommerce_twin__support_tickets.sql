-- resolution_days is -1 for tickets without a resolution.
select
    assumeNotNull(ticket_id) as ticket_id,
    assumeNotNull(customer_id) as customer_id,
    assumeNotNull(order_id) as order_id,
    toDate(assumeNotNull(created_date)) as created_date,
    assumeNotNull(category) as category,
    assumeNotNull(priority) as priority,
    assumeNotNull(status) as status,
    assumeNotNull(resolution_days) as resolution_days
from {{ source('ecommerce_twin', 'support_tickets') }}
