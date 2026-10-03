"""Heavy run (TEAM_PLAN §5 Phase 3, C): train SetFit on the LLM labels, check the F1 gate on the
held-out public labels, then backfill every redacted note and transcript into text.extractions.

    uv run python scripts/backfill.py [--labels data/labels/llm_labels_extract-v4.jsonl] [--force]

Steps (GPU): fit SetFitBackfill on the LLM hardship labels -> save to data/models/setfit/ -> gate on
the 30% held-out public labels (notes + transcripts; hardship recall >= 0.90, F1 >= 0.80) -> predict
once per distinct text of the latest redacted_notes Parquet -> write text.extractions (rows that
already hold an LLM extraction are kept) and export data/exports/extractions/ for the hand-over.
Without --force, a failed gate stops before the backfill.
"""

from __future__ import annotations

import argparse
import glob
import json
import subprocess
import time
import warnings
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from kept.common.db import connect
from kept.config import WAREHOUSE_PATH
from kept.contracts.enums import HardshipSignal
from kept.text.backfill import MODEL_VERSION, SetFitBackfill
from kept.text.evaluate import text_feature_gate
from kept.text.extract import FIELDS
from kept.text.labels import load_labels
from kept.text.redact import stored_redacted
from kept.text.store import COLUMNS, DDL, from_row

DATA = Path("data")
PUBLIC = {
    "note": DATA / "labels/agent_notes_labels_public_500.csv",
    "transcript": DATA / "labels/call_transcripts_labels_public_500.csv",
}
NOTHING = {  # SetFit predicts hardship only; every other field gets its nothing-found value
    "stated_reason": "none",
    "promise_intent": False,
    "promised_date": None,
    "promised_amount": None,
    "dispute": False,
    "cease_request": False,
    "third_party_present": False,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", type=Path, default=DATA / "labels/llm_labels_extract-v4.jsonl")
    ap.add_argument("--force", action="store_true", help="backfill even if the gate fails")
    args = ap.parse_args()
    warnings.filterwarnings("ignore")
    t0 = time.time()
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True
    ).stdout.strip()

    src = sorted(glob.glob(str(DATA / "exports/redacted_notes/redacted_notes_*.parquet")))[-1]
    notes = pd.read_parquet(src)
    version = str(notes["redactor_version"].iloc[0])
    print(f"{len(notes):,} redacted texts from {src}", flush=True)

    # 1. train on the LLM hardship labels
    rows = [json.loads(line) for line in args.labels.open()]
    rows = [r for r in rows if "extraction" in r]
    texts = [stored_redacted(r["text"], version) for r in rows]
    labels = [HardshipSignal(r["extraction"]["hardship_signal"]["value"]) for r in rows]
    counts = pd.Series([str(y) for y in labels]).value_counts().to_dict()
    print(f"training on {len(rows):,} LLM labels {counts}", flush=True)
    model = SetFitBackfill()
    model.fit(texts, labels)
    model_dir = DATA / f"models/setfit/{MODEL_VERSION}_{commit}"
    model.save(model_dir)
    print(f"trained in {time.time() - t0:.0f}s -> {model_dir}", flush=True)

    # 2. gate on the held-out public labels (never used for prompt tuning or training)
    by_id = notes.set_index("source_id")["text"]
    passed = True
    for kind, path in PUBLIC.items():
        held = [r for r in load_labels(path) if r["holdout"] and r["source_id"] in by_id.index]
        pred = model.predict([stored_redacted(by_id[r["source_id"]], version) for r in held])
        g = text_feature_gate(
            "hardship_signal",
            [r["hardship_signal"] is not HardshipSignal.NONE for r in held],
            [p is not HardshipSignal.NONE for p in pred],
        )
        passed &= g.passed
        print(
            f"gate {kind}s (n={g.n}): f1 {g.f1:.3f} p {g.precision:.3f} r {g.recall:.3f} {g.reason}",
            flush=True,
        )
    if not passed and not args.force:
        raise SystemExit("gate failed: not backfilling (rerun with --force to backfill anyway)")

    # 3. predict once per distinct text, spread to every note/transcript with that text
    distinct = notes["text"].drop_duplicates().tolist()
    x = model.extractions(
        [stored_redacted(t, version) for t in distinct],
        source_ids=[str(i) for i in range(len(distinct))],
        case_ids=[""] * len(distinct),
    )
    hardship = dict(
        zip(distinct, ((e.hardship_signal.value.value, e.hardship_signal.confidence) for e in x), strict=True)
    )
    print(f"predicted {len(distinct):,} distinct texts in {time.time() - t0:.0f}s", flush=True)

    out = pd.DataFrame({"source_id": notes["source_id"], "case_id": notes["case_id"]})
    for f in FIELDS:
        value = notes["text"].map(lambda t: hardship[t][0]) if f == "hardship_signal" else NOTHING[f]
        conf = notes["text"].map(lambda t: hardship[t][1]) if f == "hardship_signal" else 0.0
        out[f"{f}_value"], out[f"{f}_quote"], out[f"{f}_char_start"], out[f"{f}_char_end"] = (
            value,
            None,
            None,
            None,
        )
        out[f"{f}_confidence"] = conf
    out["extractor"] = f"setfit:{MODEL_VERSION}"
    out["extracted_at"] = datetime.now(UTC)
    out["confirmed_by_agent_id"] = None
    out = out[list(COLUMNS)]
    from_row(tuple(out.iloc[0]))  # the rows must round-trip into the TextExtraction contract

    export = DATA / f"exports/extractions/extractions_{commit}_{date.today():%Y%m%d}.parquet"
    export.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(export, index=False)

    with connect(WAREHOUSE_PATH) as c:  # one writer (K5)
        c.execute(DDL)
        c.register("backfill", out)
        c.execute(
            "insert or replace into text.extractions select * from backfill b "
            "where b.source_id not in (select source_id from text.extractions where extractor like 'llm:%')"
        )
        n, positive = c.execute(
            "select count(*), count(*) filter (where hardship_signal_value <> 'none') from text.extractions"
        ).fetchone()  # type: ignore[misc]
    print(
        f"text.extractions: {n:,} rows, {positive:,} with hardship; export {export} ({time.time() - t0:.0f}s)"
    )


if __name__ == "__main__":
    main()
