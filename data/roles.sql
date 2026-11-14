-- Read-only role the agent connects as. The password is passed in on the
-- command line so it never lives in this file:
--   psql -U postgres -d retail -v ro_password='choose-a-password' -f data/roles.sql
-- (Fails if the role already exists; drop it first to re-run.)

CREATE ROLE sql_agent_ro LOGIN PASSWORD :'ro_password';

GRANT CONNECT ON DATABASE :"DBNAME" TO sql_agent_ro;
GRANT USAGE ON SCHEMA public TO sql_agent_ro;
GRANT SELECT ON stores, products, customers, orders, order_items TO sql_agent_ro;

-- Defence in depth: even if a write slipped past the validator, every
-- transaction for this role is read-only and long queries are cancelled.
ALTER ROLE sql_agent_ro SET default_transaction_read_only = on;
ALTER ROLE sql_agent_ro SET statement_timeout = '5s';
