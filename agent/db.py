"""PostgreSQL access: read the schema for the prompt, and run validated queries."""

from dataclasses import dataclass

import psycopg

from agent import config


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[tuple]
    truncated: bool  # True if the query returned more than MAX_ROWS rows


def _connect() -> psycopg.Connection:
    """Open a connection with a statement timeout. Raises ConnectionError on failure."""
    if not config.DATABASE_URL:
        raise ConnectionError("DATABASE_URL is not set in .env")
    try:
        return psycopg.connect(
            config.DATABASE_URL,
            options=f"-c statement_timeout={config.STATEMENT_TIMEOUT_MS}",
        )
    except psycopg.OperationalError as e:
        # Kept separate from query errors so the agent doesn't ask the LLM
        # to "fix" SQL when the real problem is the database being down.
        raise ConnectionError(f"Could not connect to PostgreSQL: {e}") from e


def get_schema_text(tables: frozenset[str] = config.ALLOWED_TABLES) -> str:
    """Describe the allowed tables, their columns and foreign keys, for the prompt.

    Reading this from the database (not hard-coding it) keeps the prompt in
    sync if the schema changes.
    """
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = ANY(%s)
            ORDER BY table_name, ordinal_position
            """,
            (list(tables),),
        )
        columns: dict[str, list[str]] = {}
        for table, column, data_type in cur.fetchall():
            columns.setdefault(table, []).append(f"{column} {data_type}")

        cur.execute(
            """
            SELECT conrelid::regclass::text, pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE contype = 'f' AND conrelid::regclass::text = ANY(%s)
            ORDER BY 1
            """,
            (list(tables),),
        )
        foreign_keys = [f"{table}: {definition}" for table, definition in cur.fetchall()]

    lines = [f"{table}({', '.join(cols)})" for table, cols in sorted(columns.items())]
    if foreign_keys:
        lines.append("")
        lines.append("Foreign keys:")
        lines.extend(foreign_keys)
    return "\n".join(lines)


def run_query(sql: str) -> QueryResult:
    """Run one validated SELECT in a read-only transaction.

    Raises ConnectionError if the database is unreachable, and psycopg.Error
    if the query itself fails (bad column, timeout, ...).
    """
    with _connect() as conn:
        conn.read_only = True  # must be set before the transaction starts
        with conn.cursor() as cur:
            # No params are passed, so psycopg sends the SQL as-is and a '%'
            # in LIKE '%x%' is not treated as a placeholder.
            cur.execute(sql)
            columns = [col.name for col in cur.description]
            # Fetch one extra row only to know whether the result was cut off.
            rows = cur.fetchmany(config.MAX_ROWS + 1)

    truncated = len(rows) > config.MAX_ROWS
    return QueryResult(columns=columns, rows=rows[: config.MAX_ROWS], truncated=truncated)
