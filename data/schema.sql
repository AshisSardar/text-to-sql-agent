-- Sample retail schema for the Text-to-SQL agent.
-- Run as the database owner:  psql -U postgres -d retail -f data/schema.sql

DROP TABLE IF EXISTS order_items, orders, customers, products, stores;

CREATE TABLE stores (
    store_id  serial PRIMARY KEY,
    name      text NOT NULL,
    city      text NOT NULL
);

CREATE TABLE products (
    product_id serial PRIMARY KEY,
    name       text NOT NULL,
    category   text NOT NULL,
    price      numeric(10, 2) NOT NULL CHECK (price > 0)
);

CREATE TABLE customers (
    customer_id serial PRIMARY KEY,
    name        text NOT NULL,
    city        text NOT NULL
);

CREATE TABLE orders (
    order_id     serial PRIMARY KEY,
    customer_id  int NOT NULL REFERENCES customers (customer_id),
    store_id     int NOT NULL REFERENCES stores (store_id),
    order_date   date NOT NULL,
    total_amount numeric(12, 2) NOT NULL DEFAULT 0
);

CREATE TABLE order_items (
    order_item_id serial PRIMARY KEY,
    order_id      int NOT NULL REFERENCES orders (order_id) ON DELETE CASCADE,
    product_id    int NOT NULL REFERENCES products (product_id),
    quantity      int NOT NULL CHECK (quantity > 0),
    unit_price    numeric(10, 2) NOT NULL
);

CREATE INDEX ON orders (order_date);
CREATE INDEX ON order_items (order_id);
CREATE INDEX ON order_items (product_id);
