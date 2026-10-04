# ruff: noqa: E501
"""Ask every question in a questions CSV through a running `kept serve` (POST /bench/question, the Bench page's
route) and write the answers CSV in the organisers' template, plus a results JSON for the benchmark report.

    uv run python scripts/bench_run.py data/benchmark/benchmark_questions.csv --gold data/benchmark/benchmark_dev_answers.csv
    uv run python scripts/bench_run.py benchmarks/stress_questions.csv --gold benchmarks/stress_gold.csv \\
        --out data/exports/reports/stress_answers.csv

Same rows as `kept benchmark` (the server asks each question the same way), without stopping the server. Paced,
and a question that fails is retried, because the free LLM tier rate-limits by the minute.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
COLUMNS = ["question_id", "answer", "sql_or_sources", "refused"]


def ask(api: str, question: dict[str, str], gold: dict[str, str] | None) -> dict[str, object]:
    body = json.dumps({"question": question, "gold": gold}).encode()
    req = urllib.request.Request(
        f"{api}/bench/question", data=body, headers={"content-type": "application/json"}
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.load(r)  # type: ignore[no-any-return]
        except Exception as e:  # rate limit or a dropped connection: wait and ask again
            if attempt == 2:
                raise
            print(f"  {question['question_id']}: {e}; retrying in 20 s", flush=True)
            time.sleep(20)
    raise AssertionError("unreachable")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("questions", type=Path)
    ap.add_argument("--gold", type=Path)
    ap.add_argument("--out", type=Path, default=REPO / "submission" / "benchmark_answers.csv")
    ap.add_argument("--json", type=Path, help="results for the report (default: next to --out)")
    ap.add_argument("--api", default="http://localhost:8000")
    a = ap.parse_args()
    with a.questions.open(encoding="utf-8", newline="") as f:
        questions = list(csv.DictReader(f))
    gold: dict[str, dict[str, str]] = {}
    if a.gold:
        with a.gold.open(encoding="utf-8", newline="") as f:
            gold = {r["question_id"]: r for r in csv.DictReader(f)}
    results = []
    for q in questions:
        r = ask(a.api, q, gold.get(q["question_id"]))
        if "couldn't tell" in str(r["row"]["answer"]):  # type: ignore[index]  # the scope check's LLM call failed
            time.sleep(30)  # (rate limit): a transient error, not a decision, so ask once more
            r = ask(a.api, q, gold.get(q["question_id"]))
        results.append(r)
        mark = {True: "right", False: "WRONG", None: ""}[r["correct"]]  # type: ignore[index]
        print(f"{q['question_id']:8} {r['rung']:10} {mark:6} {int(r['ms']) / 1000:5.1f}s", flush=True)  # type: ignore[call-overload]
        time.sleep(5)  # stay under the free tier's per-minute limit
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with a.out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, COLUMNS)
        w.writeheader()
        for r in results:
            row = r["row"]
            w.writerow({**row, "refused": "true" if row["refused"] in (True, "true") else "false"})  # type: ignore[index, dict-item]
    out_json = a.json or a.out.with_suffix(".json")
    keep = ("rung", "correct", "should_refuse", "ms")
    out_json.write_text(
        json.dumps(
            [{"question_id": r["row"]["question_id"], **{k: r[k] for k in keep}} for r in results], indent=1
        )
    )  # type: ignore[index]
    graded = [r for r in results if r["correct"] is not None]
    print(
        f"{len(results)} answers -> {a.out}; {sum(r['correct'] is True for r in graded)}/{len(graded)} graded right"
    )


if __name__ == "__main__":
    main()
