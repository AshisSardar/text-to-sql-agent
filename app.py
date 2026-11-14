"""Streamlit web UI for the Text-to-SQL agent.

Run:  streamlit run app.py      (opens http://localhost:8501)

Streamlit re-runs this whole script from top to bottom on every click or
message. Anything that must survive a re-run lives in st.session_state, and
expensive setup (LLM client, schema) is cached with st.cache_resource.
"""

import time
from decimal import Decimal

import pandas as pd
import streamlit as st

from agent import config, db
from agent.graph import build_graph, make_llm

EXAMPLES = [
    "Which 5 products sold the most units last week?",
    "Which products had the biggest drop in revenue last week compared to the week before?",
    "What is the total revenue for each store?",
    "What share of revenue does each category account for?",
    "Try to delete all orders",
]

st.set_page_config(page_title="Text-to-SQL Agent", page_icon="🗄️", layout="wide")


@st.cache_resource
def load_agent():
    """Built once per server process, not on every re-run."""
    schema = db.get_schema_text()
    return build_graph(make_llm(), schema), schema


def to_dataframe(columns: list[str], rows: list[tuple]) -> pd.DataFrame:
    # Decimal -> float so the table renders as numbers.
    clean = [[float(v) if isinstance(v, Decimal) else v for v in row] for row in rows]
    return pd.DataFrame(clean, columns=columns)


def show_result(result: dict) -> None:
    """Render one agent answer (used for new answers and for chat history)."""
    if result.get("failed"):
        st.error(result["answer"])
    else:
        st.markdown(result["answer"])

    cols = st.columns(3)
    cols[0].metric("Attempts", result["attempts"])
    cols[1].metric("Rows", len(result["rows"]) if result.get("rows") is not None else "–")
    cols[2].metric("Time", f"{result['seconds']:.1f}s")

    if result.get("sql"):
        with st.expander("SQL used", expanded=False):
            st.code(result["sql"], language="sql")
    if result.get("rows"):
        st.dataframe(to_dataframe(result["columns"], result["rows"]), hide_index=True, width="stretch")
        if result.get("truncated"):
            st.warning(f"Result cut off at {config.MAX_ROWS} rows.")


def ask(app, question: str) -> dict:
    start = time.perf_counter()
    state = app.invoke({"question": question})
    return {
        "answer": state["answer"],
        "failed": bool(state.get("error")),
        "sql": state.get("sql"),
        "attempts": state.get("attempts", 0),
        "columns": state.get("columns", []),
        "rows": state.get("rows") if not state.get("error") else None,
        "truncated": state.get("truncated", False),
        "seconds": time.perf_counter() - start,
    }


# ---------- page ----------

st.title("Text-to-SQL Analytics Agent")
st.caption(f"Ask a business question in plain English. Model: `{config.LLM_PROVIDER} / {config.LLM_MODEL}`")

try:
    app, schema = load_agent()
except ConnectionError as e:
    st.error(f"{e}\n\nIs the PostgreSQL service running and DATABASE_URL set in .env?")
    st.stop()

if "history" not in st.session_state:
    st.session_state.history = []  # list of (question, result) pairs

with st.sidebar:
    st.subheader("Try an example")
    for example in EXAMPLES:
        if st.button(example, width="stretch"):
            st.session_state.pending = example
    st.divider()
    with st.expander("Database schema"):
        st.code(schema, language="text")
    st.caption(
        "Safety: only single read-only SELECTs on the 5 retail tables pass the validator; "
        f"queries run as a read-only role with a {config.STATEMENT_TIMEOUT_MS / 1000:.0f}s timeout "
        f"and at most {config.MAX_ROWS} rows."
    )
    if st.button("Clear chat"):
        st.session_state.history = []
        st.rerun()

for question, result in st.session_state.history:
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        show_result(result)

typed = st.chat_input("e.g. Which store had the most orders last month?")
question = typed or st.session_state.pop("pending", None)

if question:
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        with st.spinner("Writing SQL, checking it, running it..."):
            try:
                result = ask(app, question)
            except ConnectionError as e:
                st.error(str(e))
                st.stop()
            except Exception as e:  # e.g. LLM API errors such as rate limits
                st.error(f"The model call failed: {type(e).__name__}: {e}")
                st.stop()
        show_result(result)
    st.session_state.history.append((question, result))
