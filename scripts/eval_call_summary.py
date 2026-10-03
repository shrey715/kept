"""Score kept.text.calls against the public gold summaries (label_summary_gold), plus BQ-016/021/022.

    uv run python scripts/eval_call_summary.py [N] [--model ollama/gemma3:12b-it-qat]

Reads the redacted transcripts straight from the Parquet export (no warehouse lock needed). Prints exact
matches and per-part accuracy (reason, promise, next step) over the first N labelled transcripts.
"""

from __future__ import annotations

import argparse
import csv
import glob
import tempfile

import duckdb

from kept.common.audit import DuckDBAuditLog
from kept.common.llm import LiteLLMGateway
from kept.text.calls import summarise_call

BENCH = {
    "CS-2026-614370": "Customer reports illness; promised $95 on 14 Oct; next step: hardship plan review.",
    "CS-2026-619801": None,  # test split: no gold
    "CS-2026-855160": "Customer reports reduced hours / income; promised $595 on 5 Oct; "
    "asked to stop contact; next step: stop contact.",
}


def parts(s: str) -> dict[str, str]:
    p = [x.strip() for x in s.rstrip(".").split(";")]
    return {
        "reason": next((x for x in p if x.startswith("Customer")), ""),
        "promise": next((x for x in p if x.startswith("promised")), ""),
        "next": next((x for x in p if x.startswith("next step")), ""),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("n", type=int, nargs="?", default=100)
    ap.add_argument("--model", default="ollama/gemma3:12b-it-qat")
    a = ap.parse_args()
    conn = duckdb.connect()
    conn.execute("create schema text")
    src = sorted(glob.glob("data/exports/redacted_notes/*.parquet"))[-1]
    conn.execute(f"create view text.redacted_notes as select * from read_parquet('{src}')")
    llm = LiteLLMGateway(model=a.model, audit_log=DuckDBAuditLog(tempfile.mktemp(suffix=".duckdb")))

    for case, gold in BENCH.items():
        got = summarise_call(case, llm=llm, conn=conn)
        print(case, got.transcript_id if got else None, "|", got.summary if got else None)
        if gold:
            print("   gold:", gold, "| match:", bool(got and got.summary == gold))

    with open("data/labels/call_transcripts_labels_public_500.csv") as f:
        labels = list(csv.DictReader(f))[: a.n]
    exact, hits = 0, {"reason": 0, "promise": 0, "next": 0}
    for r in labels:
        case = conn.execute(
            "select case_id from text.redacted_notes where source_id = ?", [r["transcript_id"]]
        ).fetchone()
        # summarise this transcript: the newest call for its case may be a different one, so pin it
        got = summarise_call(
            case[0],
            llm=llm,
            conn=_only(conn, r["transcript_id"]),
        )
        gold = r["label_summary_gold"]
        exact += got is not None and got.summary == gold
        g, s = parts(gold), parts(got.summary if got else "")
        for k in hits:
            hits[k] += g[k] == s[k]
        if got and got.summary != gold:
            print(
                f"  {r['transcript_id']}: got  {got.summary}\n  {' ' * len(r['transcript_id'])}  gold {gold}"
            )
    n = len(labels)
    print(
        f"\n{n} labelled: exact {exact}/{n} ({exact / n:.0%}) · "
        + " · ".join(f"{k} {v / n:.0%}" for k, v in hits.items())
    )


def _only(conn: duckdb.DuckDBPyConnection, transcript_id: str) -> duckdb.DuckDBPyConnection:
    c = duckdb.connect()
    c.execute("create schema text")
    row = conn.execute("select * from text.redacted_notes where source_id = ?", [transcript_id]).arrow()
    c.register("row_", row)
    c.execute("create table text.redacted_notes as select * from row_")
    return c


if __name__ == "__main__":
    main()
