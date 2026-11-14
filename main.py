"""Command-line entry point.

    python main.py "Which 5 products sold the most units last week?"
    python main.py            # interactive: type questions, blank line to quit
"""

import sys
import time

from agent import db, prompts
from agent.graph import build_graph, make_llm


def ask(app, question: str) -> None:
    start = time.perf_counter()
    state = app.invoke({"question": question})
    elapsed = time.perf_counter() - start

    print(f"\nSQL (attempt {state['attempts']}):\n{state['sql']}\n")
    if "rows" in state and not state.get("error"):
        print(prompts.format_table(state["columns"], state["rows"], limit=20))
        if state.get("truncated"):
            print("(result truncated at MAX_ROWS)")
        print()
    print(f"Answer: {state['answer']}")
    print(f"({elapsed:.1f}s)\n")


def main() -> None:
    app = build_graph(make_llm(), db.get_schema_text())

    if len(sys.argv) > 1:
        ask(app, " ".join(sys.argv[1:]))
        return

    while question := input("Question (blank to quit): ").strip():
        ask(app, question)


if __name__ == "__main__":
    main()
