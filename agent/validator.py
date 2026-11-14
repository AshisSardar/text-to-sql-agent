"""Read-only safety checks for LLM-generated SQL.

The SQL is parsed into a syntax tree with sqlglot (PostgreSQL dialect) and
the tree is inspected. This avoids the classic regex mistakes, such as
flagging the word "delete" inside a string, or missing a DELETE hidden
inside a CTE.

This is the first safety layer. The second is the database itself: the agent
connects as a read-only role that can only SELECT from the allowed tables.
"""

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

# Node types that change data or schema, or run arbitrary commands.
_FORBIDDEN_NODES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.TruncateTable,
    exp.Grant,
    exp.Command,  # anything sqlglot doesn't model, e.g. COPY, VACUUM, DO
)

# Functions that can read server files, sleep, or change settings.
_FORBIDDEN_FUNCTION_PREFIXES = ("pg_", "lo_", "dblink")
_FORBIDDEN_FUNCTIONS = {"set_config", "current_setting", "query_to_xml"}


def validate_sql(sql: str, allowed_tables: frozenset[str]) -> str | None:
    """Return None if the SQL is safe to run, otherwise a reason it was rejected."""
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except ParseError as e:
        return f"Could not parse the SQL: {e}"

    if len(statements) != 1:
        return f"Exactly one statement is allowed, got {len(statements)}."
    tree = statements[0]

    # exp.Query covers SELECT and UNION/INTERSECT/EXCEPT (with or without WITH).
    if not isinstance(tree, exp.Query):
        return f"Only SELECT queries are allowed, got {tree.key.upper()}."

    forbidden = tree.find(*_FORBIDDEN_NODES)
    if forbidden is not None:
        return f"{forbidden.key.upper()} is not allowed; queries must be read-only."

    for select in tree.find_all(exp.Select):
        if select.args.get("into"):
            return "SELECT ... INTO creates a table and is not allowed."
        if select.args.get("locks"):
            return "Row locking clauses (FOR UPDATE / FOR SHARE) are not allowed."

    for func in tree.find_all(exp.Anonymous):
        name = func.name.lower()
        if name.startswith(_FORBIDDEN_FUNCTION_PREFIXES) or name in _FORBIDDEN_FUNCTIONS:
            return f"Function {name}() is not allowed."

    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):
        schema, name = table.db.lower(), table.name.lower()
        if schema and schema != "public":
            return f"Schema '{schema}' is not allowed. Use only: {', '.join(sorted(allowed_tables))}."
        if not schema and name in cte_names:
            continue
        if name not in allowed_tables:
            return f"Table '{name or table.sql()}' is not allowed. Use only: {', '.join(sorted(allowed_tables))}."

    return None
