-- Sample data. Order dates are relative to CURRENT_DATE (last 90 days), so
-- questions like "last week" always have data. setseed() makes the random
-- values repeatable on the same PostgreSQL version.
-- Run after schema.sql:  psql -U postgres -d retail -f data/seed.sql

SELECT setseed(0.42);

INSERT INTO stores (name, city) VALUES
    ('Park Street',     'Kolkata'),
    ('Salt Lake',       'Kolkata'),
    ('Andheri',         'Mumbai'),
    ('Connaught Place', 'Delhi'),
    ('Koramangala',     'Bengaluru');

INSERT INTO products (name, category, price) VALUES
    ('Basmati Rice 5kg',     'Grocery',     649.00),
    ('Sunflower Oil 1L',     'Grocery',     189.00),
    ('Darjeeling Tea 250g',  'Grocery',     325.00),
    ('Masoor Dal 1kg',       'Grocery',     139.00),
    ('Cotton Kurta',         'Apparel',     899.00),
    ('Denim Jeans',          'Apparel',    1499.00),
    ('Running Shoes',        'Footwear',   2799.00),
    ('Leather Sandals',      'Footwear',   1199.00),
    ('Bluetooth Earbuds',    'Electronics', 1999.00),
    ('Power Bank 10000mAh',  'Electronics', 1299.00),
    ('LED Desk Lamp',        'Electronics',  849.00),
    ('Steel Water Bottle',   'Home',         399.00),
    ('Non-stick Tawa',       'Home',         749.00),
    ('Bedsheet Set',         'Home',        1099.00),
    ('Face Wash 100ml',      'Personal Care', 199.00);

INSERT INTO customers (name, city)
SELECT 'Customer ' || g,
       (ARRAY['Kolkata', 'Mumbai', 'Delhi', 'Bengaluru', 'Chennai'])[1 + floor(random() * 5)::int]
FROM generate_series(1, 200) AS g;

INSERT INTO orders (customer_id, store_id, order_date)
SELECT 1 + floor(random() * 200)::int,
       1 + floor(random() * 5)::int,
       CURRENT_DATE - (1 + floor(random() * 90)::int)
FROM generate_series(1, 2000);

-- 1 to 3 random products per order. The "o.order_id IS NOT NULL" condition
-- makes the subquery correlated, so PostgreSQL re-runs it for every order
-- instead of picking the same products once.
INSERT INTO order_items (order_id, product_id, quantity, unit_price)
SELECT o.order_id, p.product_id, 1 + floor(random() * 3)::int, p.price
FROM orders AS o
CROSS JOIN LATERAL (
    SELECT product_id, price
    FROM products
    WHERE o.order_id IS NOT NULL
    ORDER BY random()
    LIMIT 1 + floor(random() * 3)::int
) AS p;

UPDATE orders AS o
SET total_amount = s.total
FROM (
    SELECT order_id, SUM(quantity * unit_price) AS total
    FROM order_items
    GROUP BY order_id
) AS s
WHERE s.order_id = o.order_id;
