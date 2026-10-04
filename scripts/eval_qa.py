"""Score kept.text.qa against the release's QA labels (public 500 transcripts).

    uv run python scripts/eval_qa.py [N] [--model ollama/gemma3:12b-it-qat]

Reads the redacted transcripts from the Parquet export (no warehouse needed). Prints per-item accuracy, the
coaching flag's precision and recall, and the score's mean absolute error. Item 6 needs the account balance,
so the label's own item 6 is used when comparing scores.
"""

from __future__ import annotations

import argparse
import csv
import glob
import tempfile

import duckdb

from kept.common.audit import DuckDBAuditLog
from kept.common.llm import LiteLLMGateway
from kept.text.qa import ITEMS, NEEDS_ACCOUNT, score, score_call
from kept.text.redact import stored_redacted


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("n", type=int, nargs="?", default=100)
    ap.add_argument("--model", default="ollama/gemma3:12b-it-qat")
    a = ap.parse_args()
    src = sorted(glob.glob("data/exports/redacted_notes/*.parquet"))[-1]
    con = duckdb.connect()
    llm = LiteLLMGateway(model=a.model, audit_log=DuckDBAuditLog(tempfile.mktemp(suffix=".duckdb")))
    with open("data/labels/call_transcripts_labels_public_500.csv") as f:
        labels = list(csv.DictReader(f))[: a.n]
    codes = list(ITEMS)
    right = dict.fromkeys(codes, 0)
    tp = fp = fn = 0
    err = 0
    for r in labels:
        row = con.execute(
            f"select text, redactor_version from read_parquet('{src}') where source_id = ?",
            [r["transcript_id"]],
        ).fetchone()
        assert row is not None
        got = score_call(stored_redacted(row[0], row[1]), llm=llm)
        gold = {c: r[f"qa{i + 1:02d}_{c}"] for i, c in enumerate(codes)}
        for c in codes:
            right[c] += got.items[c] == gold[c]
        mine, coach = score(got.items | {NEEDS_ACCOUNT: gold[NEEDS_ACCOUNT]})
        want = r["qa_coaching_required"] == "true"
        tp, fp, fn = tp + (coach and want), fp + (coach and not want), fn + (want and not coach)
        err += abs(mine - int(r["qa_total_score"]))
    n = len(labels)
    print(f"{n} labelled calls")
    for c in codes:
        acc = "(needs the account)" if c == NEEDS_ACCOUNT else f"{right[c] / n:.0%}"
        print(f"  {c:<40} {acc}")
    prec, rec = tp / max(tp + fp, 1), tp / max(tp + fn, 1)
    print(f"coaching flag: precision {prec:.0%}, recall {rec:.0%} ({tp + fn} true)")
    print(f"score: mean absolute error {err / n:.1f} points")


if __name__ == "__main__":
    main()
