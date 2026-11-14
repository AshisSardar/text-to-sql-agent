"""Graph tests with a fake LLM and fake database, so no API key or Postgres is needed."""

import psycopg
from langchain_core.language_models import FakeListChatModel

from agent import config
from agent.db import QueryResult
from agent.graph import build_graph

SCHEMA = "orders(order_id integer, order_date date, total_amount numeric)"


def fake_db(bad_column: str | None = None):
    """A run_query stand-in. Raises like Postgres if the SQL mentions bad_column."""
    calls = []

    def run_query(sql: str) -> QueryResult:
        calls.append(sql)
        if bad_column and bad_column in sql:
            raise psycopg.errors.UndefinedColumn(f'column "{bad_column}" does not exist')
        return QueryResult(columns=["n"], rows=[(42,)], truncated=False)

    run_query.calls = calls
    return run_query


def test_happy_path():
    llm = FakeListChatModel(responses=["```sql\nSELECT COUNT(*) AS n FROM orders;\n```", "There are 42 orders."])
    run_query = fake_db()
    state = build_graph(llm, SCHEMA, run_query).invoke({"question": "How many orders?"})

    assert state["sql"] == "SELECT COUNT(*) AS n FROM orders"
    assert state["attempts"] == 1
    assert state["rows"] == [(42,)]
    assert state["answer"] == "There are 42 orders."


def test_database_error_is_fixed_by_retry():
    llm = FakeListChatModel(responses=[
        "```sql\nSELECT SUM(amount) AS n FROM orders\n```",        # wrong column
        "```sql\nSELECT SUM(total_amount) AS n FROM orders\n```",  # fixed
        "Total sales are 42.",
    ])
    run_query = fake_db(bad_column="(amount)")
    state = build_graph(llm, SCHEMA, run_query).invoke({"question": "Total sales?"})

    assert state["attempts"] == 2
    assert len(run_query.calls) == 2
    assert state["answer"] == "Total sales are 42."


def test_unsafe_sql_is_never_executed():
    llm = FakeListChatModel(responses=["```sql\nDELETE FROM orders\n```"] * config.MAX_ATTEMPTS)
    run_query = fake_db()
    state = build_graph(llm, SCHEMA, run_query).invoke({"question": "Delete everything"})

    assert run_query.calls == []
    assert state["attempts"] == config.MAX_ATTEMPTS
    assert state["answer"].startswith("Sorry")


def test_summarize_false_makes_only_one_llm_call():
    # Only one response is queued: a second LLM call would get it again and
    # the answer would not be empty.
    llm = FakeListChatModel(responses=["```sql\nSELECT COUNT(*) AS n FROM orders\n```"])
    state = build_graph(llm, SCHEMA, fake_db(), summarize=False).invoke({"question": "How many orders?"})

    assert state["rows"] == [(42,)]
    assert state["answer"] == ""
