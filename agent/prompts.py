"""Prompt templates and helpers for the agent's two LLM calls."""

import re
from datetime import date

SQL_SYSTEM_PROMPT = """You are a PostgreSQL expert. Write one SQL query that answers the user's question about a retail database.

Database schema:
{schema}

Rules:
- Write exactly one read-only SELECT statement (CTEs with WITH are fine).
- Use only the tables and columns in the schema above.
- Today's date is {today} ({weekday}). Resolve relative dates from it.
- Weeks are calendar weeks, Monday to Sunday. "Last week" means the previous full Monday-Sunday week; "this week" means from this Monday to today; "the week before" means the week before last week. Months work the same way ("last month" = the previous full calendar month).
- Give result columns clear names with AS.
- Unless the user asks for everything, keep results small (for example LIMIT 50 for lists).
- Reply with only the SQL inside a ```sql code block, no explanation."""

SQL_FIX_PROMPT = """Question: {question}

Your previous query:
```sql
{sql}
```

It failed with this error:
{error}

Write a corrected query."""

ANSWER_SYSTEM_PROMPT = """You explain database query results to a business user.
Answer the question in 1 to 4 plain sentences using only the result rows given.
Mention key numbers. If the result is empty, say no matching data was found.
Do not invent data that is not in the rows."""

ANSWER_PROMPT = """Question: {question}

SQL used:
```sql
{sql}
```

Result ({row_count} rows{truncated_note}):
{table}"""

# How many rows to show the LLM when summarizing. The full result is still
# returned to the user; this only keeps the prompt small.
ROWS_FOR_SUMMARY = 50


def sql_system_prompt(schema: str) -> str:
    today = date.today()
    return SQL_SYSTEM_PROMPT.format(schema=schema, today=today.isoformat(), weekday=today.strftime("%A"))


def extract_sql(text: str) -> str:
    """Pull the SQL out of a ```sql block; fall back to the whole reply."""
    match = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    sql = match.group(1) if match else text
    return sql.strip().rstrip(";").strip()


def format_table(columns: list[str], rows: list[tuple], limit: int = ROWS_FOR_SUMMARY) -> str:
    """Render rows as a simple pipe-separated table for the prompt or terminal."""
    lines = [" | ".join(columns)]
    lines += [" | ".join("NULL" if v is None else str(v) for v in row) for row in rows[:limit]]
    if len(rows) > limit:
        lines.append(f"... ({len(rows) - limit} more rows)")
    return "\n".join(lines)
