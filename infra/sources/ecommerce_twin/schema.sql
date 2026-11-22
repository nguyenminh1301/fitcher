-- The seven Free Synthetic E-commerce Twin tables as a company's own PostgreSQL would hold them: typed columns,
-- primary keys and the foreign keys the data implies. seed.sh loads the rows first and adds the keys after.
CREATE TABLE customers (
    customer_id text PRIMARY KEY, signup_date date, region text, segment text, lifetime_orders integer,
    lifetime_spend numeric(14, 2), email_domain text);
CREATE TABLE products (
    product_id text PRIMARY KEY, category text, subcategory text, price numeric(12, 2), cost numeric(12, 2), brand text,
    launch_date date, avg_rating real);
CREATE TABLE sessions (
    session_id text PRIMARY KEY, customer_id text, session_start date, device text, channel text, pages_viewed integer,
    converted boolean);
CREATE TABLE orders (
    order_id text PRIMARY KEY, customer_id text, session_id text, order_date date, status text, item_count integer,
    order_total numeric(14, 2), payment_method text);
CREATE TABLE order_items (
    order_item_id text PRIMARY KEY, order_id text, product_id text, quantity integer, unit_price numeric(12, 2),
    line_total numeric(14, 2));
CREATE TABLE returns (
    return_id text PRIMARY KEY, order_id text, order_item_id text, product_id text, return_date date, reason text,
    refund_amount numeric(14, 2));
CREATE TABLE support_tickets (
    ticket_id text PRIMARY KEY, customer_id text, order_id text, created_date date, category text, priority text,
    status text, resolution_days integer);
