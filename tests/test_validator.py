import pytest

from agent.config import ALLOWED_TABLES
from agent.validator import validate_sql

SAFE = [
    "SELECT * FROM orders",
    "SELECT name FROM products WHERE name LIKE '%delete%'",  # keyword inside a string is fine
    "SELECT o.order_id FROM orders o JOIN customers c ON c.customer_id = o.customer_id",
    "SELECT * FROM public.stores",
    "WITH weekly AS (SELECT store_id, SUM(total_amount) AS s FROM orders GROUP BY 1) SELECT * FROM weekly",
    "SELECT EXTRACT(YEAR FROM order_date) AS y, COUNT(*) FROM orders GROUP BY 1",
    "SELECT city FROM stores UNION SELECT city FROM customers",
    "SELECT * FROM orders;",  # one trailing semicolon is still one statement
]

DANGEROUS = [
    "DELETE FROM orders",
    "UPDATE products SET price = 0",
    "INSERT INTO stores (name, city) VALUES ('x', 'y')",
    "DROP TABLE orders",
    "TRUNCATE orders",
    "ALTER TABLE orders ADD COLUMN x int",
    "CREATE TABLE t (id int)",
    "GRANT ALL ON orders TO public",
    "SELECT 1; DROP TABLE orders",
    "WITH gone AS (DELETE FROM orders RETURNING *) SELECT * FROM gone",
    "SELECT * INTO backup FROM orders",
    "SELECT * FROM orders FOR UPDATE",
    "SELECT pg_sleep(60)",
    "SELECT pg_read_file('/etc/passwd')",
    "SELECT set_config('statement_timeout', '0', false)",
    "SELECT * FROM pg_catalog.pg_user",
    "SELECT * FROM information_schema.tables",
    "SELECT * FROM employees",
    "COPY orders TO '/tmp/out.csv'",
    "EXPLAIN ANALYZE SELECT * FROM orders",
]


@pytest.mark.parametrize("sql", SAFE)
def test_safe_queries_pass(sql):
    assert validate_sql(sql, ALLOWED_TABLES) is None


@pytest.mark.parametrize("sql", DANGEROUS)
def test_dangerous_queries_rejected(sql):
    assert validate_sql(sql, ALLOWED_TABLES) is not None
