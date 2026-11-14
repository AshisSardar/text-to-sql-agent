"""Measure the agent's accuracy on eval/questions.json.

For each question, the agent's SQL and the hand-written expected SQL both run
against the live database and their RESULTS are compared (not the SQL text,
since many different queries are correct). Running both at the same time also
keeps "last week" questions valid as the sample data's dates move.

A result counts as correct when:
  - it has the same number of rows as the expected result, and
  - the expected columns can be found among the agent's columns (in any
    order, extra columns allowed) with the same rows, ignoring row order.
  Numbers are compared rounded to 2 decimals, dates as YYYY-MM-DD.

Run:  python -m eval.run_eval                 # all questions
      python -m eval.run_eval --ids 1,9,15    # some questions
      python -m eval.run_eval --delay 5       # wait 5s between questions (rate limits)
      python -m eval.run_eval --resume        # reuse answers already saved for this
                                              # model; only call the LLM for the rest
"""

import argparse
import itertools
import json
import statistics
import time
from collections import Counter
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from agent import config, db
from agent.graph import build_graph, make_llm

EVAL_DIR = Path(__file__).resolve().parent


def normalize(value):
    """Make equal values compare equal: 61 == 61.00, timestamp at midnight == date."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat() if value.time() == datetime.min.time() else value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return str(value).strip()


def results_match(expected_rows: list[tuple], actual_rows: list[tuple]) -> bool:
    if len(expected_rows) != len(actual_rows):
        return False
    if not expected_rows:
        return True
    expected = [tuple(normalize(v) for v in row) for row in expected_rows]
    actual = [tuple(normalize(v) for v in row) for row in actual_rows]
    n_expected, n_actual = len(expected[0]), len(actual[0])
    if n_actual < n_expected:
        return False

    # Counter = multiset of rows, so row order doesn't matter but duplicates do.
    target = Counter(expected)
    # Try every way of picking the expected columns out of the agent's columns.
    for cols in itertools.permutations(range(n_actual), n_expected):
        if Counter(tuple(row[i] for i in cols) for row in actual) == target:
            return True
    return False


def run_one(app, q: dict) -> dict:
    record = {"id": q["id"], "difficulty": q["difficulty"], "question": q["question"]}
    start = time.perf_counter()
    try:
        state = app.invoke({"question": q["question"]})
    except Exception as e:
        # API problem (rate limit, timeout), not a wrong answer: it is left
        # out of the accuracy number and reported separately.
        record.update(status="api_error", correct=False, attempts=0, sql=None, error=f"{type(e).__name__}: {e}")
        record["seconds"] = round(time.perf_counter() - start, 1)
        return record
    record["seconds"] = round(time.perf_counter() - start, 1)
    record.update(status="done", sql=state.get("sql"), attempts=state.get("attempts", 0), error=state.get("error"))

    if state.get("error"):
        record["correct"] = False
    else:
        expected = db.run_query(q["expected_sql"])
        record["correct"] = results_match(expected.rows, state["rows"])
    return record


def summarize(all_records: list[dict], planned: int) -> dict:
    records = [r for r in all_records if r["status"] == "done"]  # answered by the agent
    total = len(records)
    correct = sum(r["correct"] for r in records)
    retried = [r for r in records if r["attempts"] > 1]
    by_difficulty = {}
    for level in ("easy", "medium", "hard"):
        group = [r for r in records if r["difficulty"] == level]
        if group:
            by_difficulty[level] = f"{sum(r['correct'] for r in group)}/{len(group)}"
    seconds = [r["seconds"] for r in records]
    return {
        "model": f"{config.LLM_PROVIDER}/{config.LLM_MODEL}",
        "questions_planned": planned,
        "questions_answered": total,
        "skipped_api_errors": sum(r["status"] == "api_error" for r in all_records),
        "not_run": planned - len(all_records),
        "correct": correct,
        "accuracy_pct": round(100 * correct / total, 1) if total else 0,
        "by_difficulty": by_difficulty,
        "correct_on_first_attempt": sum(r["correct"] and r["attempts"] == 1 for r in records),
        "needed_retry": len(retried),
        "fixed_by_retry": sum(r["correct"] for r in retried),
        "agent_gave_up": sum(bool(r["error"]) for r in records),
        "avg_seconds": round(statistics.mean(seconds), 1) if seconds else 0,
        "median_seconds": round(statistics.median(seconds), 1) if seconds else 0,
    }


def is_quota_error(record: dict) -> bool:
    """A daily/per-minute quota error: further calls would fail too, so stop."""
    err = (record.get("error") or "").upper()
    return record["status"] == "api_error" and ("429" in err or "RESOURCE_EXHAUSTED" in err or "QUOTA" in err)


def load_saved(model: str) -> dict[int, dict]:
    """Answered records (status 'done') from earlier runs of the same model.
    Newer files win, so a question re-run later replaces the older answer."""
    saved = {}
    for f in sorted((EVAL_DIR / "results").glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        if data["summary"].get("model") != model:
            continue
        for r in data["results"]:
            if r.get("status", "done") == "done":  # older files have no status field
                r["status"] = "done"
                saved[r["id"]] = r
    return saved


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", help="comma-separated question ids to run")
    parser.add_argument("--delay", type=float, default=0, help="seconds to wait between questions")
    parser.add_argument("--resume", action="store_true",
                        help="reuse answers saved earlier for this model; only ask the LLM the rest")
    args = parser.parse_args()

    questions = json.loads((EVAL_DIR / "questions.json").read_text(encoding="utf-8"))
    if args.ids:
        wanted = {int(i) for i in args.ids.split(",")}
        questions = [q for q in questions if q["id"] in wanted]

    model = f"{config.LLM_PROVIDER}/{config.LLM_MODEL}"
    reused = []
    if args.resume:
        saved = load_saved(model)
        reused = [saved[q["id"]] for q in questions if q["id"] in saved]
        print(f"Resume: reusing {len(reused)} saved answer(s) for {model}, "
              f"{len(questions) - len(reused)} question(s) left to ask.\n")
    to_run = [q for q in questions if q["id"] not in {r["id"] for r in reused}]

    app = build_graph(make_llm(), db.get_schema_text(), summarize=False) if to_run else None
    records = list(reused)
    api_errors_in_a_row = 0
    for i, q in enumerate(to_run):
        if i and args.delay:
            time.sleep(args.delay)
        r = run_one(app, q)
        records.append(r)
        mark = "SKIP" if r["status"] == "api_error" else ("PASS" if r["correct"] else "FAIL")
        print(f"[{mark}] #{r['id']:>2} ({r['difficulty']}, {r['attempts']} attempt(s), {r['seconds']}s) {r['question']}")
        if r["error"]:
            print(f"        error: {r['error'][:200]}")

        if is_quota_error(r):
            print("\nStopping: API quota reached. Finish later with --resume (answered questions are kept).")
            break
        api_errors_in_a_row = api_errors_in_a_row + 1 if r["status"] == "api_error" else 0
        if api_errors_in_a_row == 3:
            print("\nStopping: 3 API errors in a row. Finish later with --resume.")
            break

    records.sort(key=lambda r: r["id"])
    summary = summarize(records, planned=len(questions))
    summary["reused_from_earlier_runs"] = len(reused)
    print("\n" + json.dumps(summary, indent=2))

    out_dir = EVAL_DIR / "results"
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / f"{datetime.now():%Y%m%d-%H%M%S}.json"
    out_file.write_text(json.dumps({"summary": summary, "results": records}, indent=2, default=str), encoding="utf-8")
    print(f"Saved {out_file.relative_to(EVAL_DIR.parent)}")


if __name__ == "__main__":
    main()
