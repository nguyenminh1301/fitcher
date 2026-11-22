-- The foreign keys of the e-commerce tables, added once the rows are loaded.
ALTER TABLE sessions ADD FOREIGN KEY (customer_id) REFERENCES customers (customer_id);
ALTER TABLE orders ADD FOREIGN KEY (customer_id) REFERENCES customers (customer_id);
ALTER TABLE orders ADD FOREIGN KEY (session_id) REFERENCES sessions (session_id);
ALTER TABLE order_items ADD FOREIGN KEY (order_id) REFERENCES orders (order_id);
ALTER TABLE order_items ADD FOREIGN KEY (product_id) REFERENCES products (product_id);
ALTER TABLE returns ADD FOREIGN KEY (order_id) REFERENCES orders (order_id);
ALTER TABLE returns ADD FOREIGN KEY (order_item_id) REFERENCES order_items (order_item_id);
ALTER TABLE returns ADD FOREIGN KEY (product_id) REFERENCES products (product_id);
ALTER TABLE support_tickets ADD FOREIGN KEY (customer_id) REFERENCES customers (customer_id);
ALTER TABLE support_tickets ADD FOREIGN KEY (order_id) REFERENCES orders (order_id);
