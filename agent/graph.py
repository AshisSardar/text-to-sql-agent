"""The LangGraph flow: generate SQL -> validate -> execute -> answer, with retries.

    START -> generate_sql -> validate --ok--> execute --ok--> answer -> END
                 ^              |                 |
                 +---- error, attempts left ------+
                       (out of attempts -> answer explains the failure)

Each node is a plain function that takes the current state and returns only
the keys it changed; LangGraph merges them into the state.
"""

from typing import Callable, TypedDict

import psycopg
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from agent import config, db, prompts
from agent.validator import validate_sql


class AgentState(TypedDict, total=False):
    question: str
    sql: str
    error: str | None  # last validation/database error, None when the step succeeded
    attempts: int  # how many times SQL has been generated
    columns: list[str]
    rows: list[tuple]
    truncated: bool
    answer: str


def make_llm() -> BaseChatModel:
    """Create the chat model named in .env. Switching provider = editing .env
    and installing that provider's LangChain package (e.g. langchain-openai)."""
    return init_chat_model(
        config.LLM_MODEL,
        model_provider=config.LLM_PROVIDER,
        max_tokens=config.LLM_MAX_TOKENS,
        timeout=config.LLM_TIMEOUT_S,
        max_retries=config.LLM_MAX_RETRIES,
    )


def build_graph(
    llm: BaseChatModel,
    schema_text: str,
    run_query: Callable[[str], db.QueryResult] = db.run_query,
    summarize: bool = True,
):
    """Wire the nodes into a compiled graph.

    llm, schema_text and run_query are passed in (not created here) so tests
    can swap in a fake model and a fake database. summarize=False skips the
    final LLM call that words the answer (the eval only needs the SQL result,
    and this halves its API usage).
    """
    system_prompt = prompts.sql_system_prompt(schema_text)

    def generate_sql(state: AgentState) -> AgentState:
        if state.get("error"):
            # Retry: show the model its previous SQL and what went wrong.
            user_msg = prompts.SQL_FIX_PROMPT.format(
                question=state["question"], sql=state["sql"], error=state["error"]
            )
        else:
            user_msg = state["question"]
        reply = llm.invoke([SystemMessage(system_prompt), HumanMessage(user_msg)])
        return {
            "sql": prompts.extract_sql(reply.text),
            "attempts": state.get("attempts", 0) + 1,
            "error": None,
        }

    def validate(state: AgentState) -> AgentState:
        return {"error": validate_sql(state["sql"], config.ALLOWED_TABLES)}

    def execute(state: AgentState) -> AgentState:
        try:
            result = run_query(state["sql"])
        except psycopg.Error as e:
            # Query errors (unknown column, timeout, ...) go back to the LLM.
            # ConnectionError is not caught: retrying SQL won't fix a down database.
            return {"error": f"Database error: {e}"}
        return {
            "columns": result.columns,
            "rows": result.rows,
            "truncated": result.truncated,
            "error": None,
        }

    def answer(state: AgentState) -> AgentState:
        if state.get("error"):
            return {
                "answer": f"Sorry, I couldn't produce a working query after "
                f"{state['attempts']} attempts. Last error: {state['error']}"
            }
        rows = state["rows"]
        if not summarize:
            return {"answer": ""}
        user_msg = prompts.ANSWER_PROMPT.format(
            question=state["question"],
            sql=state["sql"],
            row_count=len(rows),
            truncated_note=", truncated" if state.get("truncated") else "",
            table=prompts.format_table(state["columns"], rows),
        )
        reply = llm.invoke([SystemMessage(prompts.ANSWER_SYSTEM_PROMPT), HumanMessage(user_msg)])
        return {"answer": reply.text}

    def route_after_check(state: AgentState) -> str:
        """Shared router for after validate and after execute."""
        if not state.get("error"):
            return "ok"
        if state["attempts"] < config.MAX_ATTEMPTS:
            return "retry"
        return "give_up"

    graph = StateGraph(AgentState)
    graph.add_node("generate_sql", generate_sql)
    graph.add_node("validate", validate)
    graph.add_node("execute", execute)
    graph.add_node("answer", answer)

    graph.add_edge(START, "generate_sql")
    graph.add_edge("generate_sql", "validate")
    graph.add_conditional_edges(
        "validate", route_after_check,
        {"ok": "execute", "retry": "generate_sql", "give_up": "answer"},
    )
    graph.add_conditional_edges(
        "execute", route_after_check,
        {"ok": "answer", "retry": "generate_sql", "give_up": "answer"},
    )
    graph.add_edge("answer", END)
    return graph.compile()
