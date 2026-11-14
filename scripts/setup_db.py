"""One-time database setup without needing psql.

Creates the `retail` database, loads data/schema.sql and data/seed.sql, and
creates the read-only role `sql_agent_ro` (same as data/roles.sql).

Needs in .env:
    ADMIN_DATABASE_URL   superuser URL to the server's `postgres` database,
                         e.g. postgresql://postgres:PASSWORD@localhost:5432/postgres
    RO_PASSWORD          password to give the read-only role

Run:  python scripts/setup_db.py
Safe to re-run: it drops and reloads the tables, and resets the role password.
"""

import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg import sql

ROOT = Path(__file__).resolve().parent.parent
DB_NAME = "retail"
RO_ROLE = "sql_agent_ro"
TABLES = ["stores", "products", "customers", "orders", "order_items"]

load_dotenv(ROOT / ".env")
admin_url = os.environ["ADMIN_DATABASE_URL"]
ro_password = os.environ["RO_PASSWORD"]

# 1. Create the database (CREATE DATABASE can't run inside a transaction).
with psycopg.connect(admin_url, autocommit=True) as conn:
    exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,)).fetchone()
    if not exists:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DB_NAME)))
        print(f"Created database {DB_NAME}")

# 2. Load schema and data, then the read-only role, in the new database.
retail_url = psycopg.conninfo.make_conninfo(admin_url, dbname=DB_NAME)
with psycopg.connect(retail_url) as conn:
    for name in ("schema.sql", "seed.sql"):
        # No params, so the file is sent as-is (multiple statements allowed).
        conn.execute((ROOT / "data" / name).read_text(encoding="utf-8"))
        print(f"Loaded data/{name}")

    role_exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (RO_ROLE,)).fetchone()
    verb = "ALTER" if role_exists else "CREATE"
    role = sql.Identifier(RO_ROLE)
    conn.execute(sql.SQL(verb + " ROLE {} LOGIN PASSWORD {}").format(role, sql.Literal(ro_password)))
    conn.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(DB_NAME), role))
    conn.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
    conn.execute(
        sql.SQL("GRANT SELECT ON {} TO {}").format(
            sql.SQL(", ").join(sql.Identifier(t) for t in TABLES), role
        )
    )
    conn.execute(sql.SQL("ALTER ROLE {} SET default_transaction_read_only = on").format(role))
    conn.execute(sql.SQL("ALTER ROLE {} SET statement_timeout = '5s'").format(role))
    print(f"{verb.title()}d read-only role {RO_ROLE}")

    counts = {t: conn.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(t))).fetchone()[0] for t in TABLES}
    print("Row counts:", counts)
