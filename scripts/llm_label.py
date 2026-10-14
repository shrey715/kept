"""Heavy run (TEAM_PLAN §5 Phase 3, C): LLM labels on ~3k redacted notes for SetFit training.

    uv run python scripts/llm_label.py [--n 3000] [--workers 6]

Samples distinct redacted texts from the latest data/exports/redacted_notes/*.parquet (never the public
label ids, so the gate stays honest): half at random, half matching hardship / rare-field wording so the
classifier sees enough positives. Runs LLMExtractor (KEPT_TEXT_LLM_MODEL, the local model) and appends one
JSON line per text to data/labels/llm_labels_<prompt>.jsonl. Reruns skip ids already labelled.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import duckdb

from kept.common.audit import DuckDBAuditLog
from kept.common.llm import LiteLLMGateway
from kept.text.extract import PROMPT_VERSION, LLMExtractor
from kept.text.redact import stored_redacted

DATA = Path("data")
HINTS = (
    r"(?i)laid off|lost (his|her|their|my)? ?job|job loss|shifts? cut|hours (cut|reduced)|reduced hours|"
    r"pay (was )?cut|sick|illness|hospital|disab|separat|divorc|passed away|deceased|funeral|evacuat|"
    r"wildfire|flood|rate reset|"
    r"renewed at|EI\b|struggl|tight|hardship|dispute|not applied|fraud|late fee|stop calling|cease|"
    r"spouse|wife|husband|3rd party|third party|son|daughter|mis à pied|perdu son emploi|heures coupées|"
    r"malad|séparation|conteste|arrêter les appels|conjoint|difficult"
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=3000)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    warnings.filterwarnings("ignore")

    src = sorted(glob.glob(str(DATA / "exports/redacted_notes/redacted_notes_*.parquet")))[-1]
    out = DATA / f"labels/llm_labels_{PROMPT_VERSION}.jsonl"
    done = {json.loads(line)["source_id"] for line in out.open()} if out.exists() else set()
    half = args.n // 2
    rows = duckdb.execute(
        f"""
        with pool as (
            select source_id, source_type, case_id, written_at_local, text,
                   row_number() over (partition by text order by hash(source_id)) as dup
            from read_parquet(?)
            where source_id not in (select note_id from read_csv(?, all_varchar=true))
              and source_id not in (select transcript_id from read_csv(?, all_varchar=true))
              and length(text) > 25
        ), distinct_texts as (select * exclude dup from pool where dup = 1)
        (select * from distinct_texts where regexp_matches(text, ?)
         order by hash(source_id || 'h') limit {half})
        union
        (select * from distinct_texts order by hash(source_id || 'r') limit {args.n - half})
        """,
        [
            src,
            str(DATA / "labels/agent_notes_labels_public_500.csv"),
            str(DATA / "labels/call_transcripts_labels_public_500.csv"),
            HINTS,
        ],
    ).fetchall()
    todo = [r for r in rows if r[0] not in done]
    print(f"{len(rows)} sampled from {src}, {len(done)} already labelled, {len(todo)} to go", flush=True)

    model = os.environ.get("KEPT_TEXT_LLM_MODEL", "llamacpp/qwen3.8-27b")
    extractor = LLMExtractor(LiteLLMGateway(model=model, audit_log=DuckDBAuditLog(), timeout_s=180))
    redactor_version = duckdb.execute(
        "select any_value(redactor_version) from read_parquet(?)", [src]
    ).fetchone()

    def one(r: tuple) -> str:  # type: ignore[type-arg]
        source_id, source_type, case_id, written_at, text = r
        redacted = stored_redacted(text, str(redactor_version[0] if redactor_version else ""))
        row = {"source_id": source_id, "source_type": source_type, "text": text}
        try:
            x = extractor.extract(
                redacted, source_id=source_id, case_id=case_id, written_at=datetime.fromisoformat(written_at)
            )
            row["extraction"] = x.model_dump(mode="json")
        except Exception as e:  # a bad reply is skipped; rerun to retry it
            row["error"] = f"{type(e).__name__}: {e}"[:300]
        return json.dumps(row, ensure_ascii=False)

    t0, n = time.time(), 0
    out.parent.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(args.workers) as pool, out.open("a") as f:
        for line in pool.map(one, todo):
            f.write(line + "\n")
            f.flush()
            n += 1
            if n % 100 == 0:
                print(f"{n}/{len(todo)} in {time.time() - t0:.0f}s", flush=True)
    print(f"done: {n} labelled in {time.time() - t0:.0f}s -> {out}")


if __name__ == "__main__":
    main()
