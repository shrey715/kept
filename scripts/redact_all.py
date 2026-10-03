"""Heavy run (TEAM_PLAN §1a): redact every agent note and call transcript -> text.redacted_notes Parquet.

    uv run python scripts/redact_all.py [--workers 4] [--limit N]

Each distinct text is redacted once (760K notes are 256K distinct texts). Output:
data/exports/redacted_notes/redacted_notes_<commit>_<date>.parquet, one row per note/transcript:
source_id, source_type (note | transcript), case_id, written_at_local, text, entity_types_removed,
redactor_version. Copy it to the shared folder for the other tracks (§1a).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import warnings
from datetime import date
from multiprocessing import Pool
from pathlib import Path

import duckdb
import pandas as pd

from kept.text.extract import transcript_text
from kept.text.redact import PresidioRedactor

DATA = Path("data")
_R: PresidioRedactor | None = None


def _init() -> None:
    global _R
    warnings.filterwarnings("ignore")
    _R = PresidioRedactor()


def _redact(text: str) -> tuple[str, str]:
    assert _R is not None
    r = _R.redact(text)
    return r.text, ",".join(r.entity_types_removed)


def load(limit: int | None) -> pd.DataFrame:
    lim = f"limit {limit}" if limit else ""
    notes = duckdb.sql(
        f"""select note_id as source_id, 'note' as source_type, case_id, note_ts as written_at_local,
        coalesce(note_text, '') as text from read_csv('{DATA}/raw/agent_notes.csv', all_varchar=true) {lim}"""
    ).df()
    calls = duckdb.sql(
        f"""select transcript_id as source_id, 'transcript' as source_type, case_id,
        call_start_ts as written_at_local, file_path
        from read_csv('{DATA}/raw/call_transcripts.csv', all_varchar=true) {lim}"""
    ).df()
    calls["text"] = [
        transcript_text(json.loads((DATA / "raw/files" / p).read_text())["turns"])
        for p in calls.pop("file_path")
    ]
    return pd.concat([notes, calls], ignore_index=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=None, help="per source, for a quick test")
    args = ap.parse_args()

    t0 = time.time()
    df = load(args.limit)
    distinct = df["text"].drop_duplicates().tolist()
    print(f"{len(df):,} texts, {len(distinct):,} distinct, loaded in {time.time() - t0:.0f}s", flush=True)
    with Pool(args.workers, initializer=_init) as pool:
        out = dict(zip(distinct, pool.imap(_redact, distinct, chunksize=256), strict=True))
    df["entity_types_removed"] = df["text"].map(lambda t: out[t][1])
    df["text"] = df["text"].map(lambda t: out[t][0])
    df["redactor_version"] = PresidioRedactor.version

    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    path = DATA / f"exports/redacted_notes/redacted_notes_{commit}_{date.today():%Y%m%d}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    changed = (df["entity_types_removed"] != "").sum()
    print(
        f"wrote {len(df):,} rows ({changed:,} with something redacted) in {time.time() - t0:.0f}s -> {path}"
    )


if __name__ == "__main__":
    main()
