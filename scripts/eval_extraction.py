"""Run the extraction prompt on the public labels and print the F1 gate per feature.

    uv run python scripts/eval_extraction.py --source notes --split tune [--limit 50] [--workers 4]
    uv run python scripts/eval_extraction.py --source transcripts --calls whisper   # or release

Redacts each text with PresidioRedactor, extracts through LiteLLMGateway (KEPT_TEXT_LLM_MODEL,
default Qwen3.8-27B on llama.cpp), and writes predictions to data/labels/runs/ for error analysis.
Tune on --split tune; check the gate once on --split holdout.
"""

from __future__ import annotations

import argparse
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
from kept.contracts import TextExtraction
from kept.text.extract import PROMPT_VERSION, LLMExtractor, transcript_text
from kept.text.labels import gate_report, load_labels
from kept.text.redact import PresidioRedactor

DATA = Path("data")
LABELS = {
    "notes": DATA / "labels/agent_notes_labels_public_500.csv",
    "transcripts": DATA / "labels/call_transcripts_labels_public_500.csv",
}


def texts(source: str, ids: list[str]) -> dict[str, tuple[str, str, datetime]]:
    """source_id -> (case_id, raw text, written_at)."""
    if source == "notes":
        rows = duckdb.execute(
            "select note_id, case_id, note_text, note_ts from read_csv(?, all_varchar=true) "
            "where note_id in ?",
            [str(DATA / "raw/agent_notes.csv"), ids],
        ).fetchall()
        return {i: (c, t or "", datetime.fromisoformat(ts)) for i, c, t, ts in rows}
    rows = duckdb.execute(
        "select transcript_id, case_id, file_path, call_start_ts from read_csv(?, all_varchar=true) "
        "where transcript_id in ?",
        [str(DATA / "raw/call_transcripts.csv"), ids],
    ).fetchall()
    out = {}
    for i, c, path, ts in rows:
        turns = json.loads((DATA / "raw/files" / path).read_text())["turns"]
        out[i] = (c, transcript_text(turns), datetime.fromisoformat(ts))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=LABELS, default="notes")
    ap.add_argument("--split", choices=["tune", "holdout"], default="tune")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument(
        "--calls",
        choices=["release", "whisper"],
        help="transcripts only: every labelled call with a recording (both splits), read from the release's "
        "transcript or from Whisper's (data/exports/voice/whisper.parquet, scripts/voice_wer.py)",
    )
    args = ap.parse_args()
    warnings.filterwarnings("ignore")

    labels = [r for r in load_labels(LABELS[args.source]) if r["holdout"] == (args.split == "holdout")]
    if args.calls:
        audio = dict(
            duckdb.execute(
                "select t.transcript_id, w.text from read_csv(?, all_varchar=true) t join read_parquet(?) w "
                "using (voice_sample_id)",
                [str(DATA / "raw/call_transcripts.csv"), str(DATA / "exports/voice/whisper.parquet")],
            ).fetchall()
        )
        labels = [r for r in load_labels(LABELS["transcripts"]) if r["source_id"] in audio]
    labels = labels[: args.limit]
    src = texts(args.source, [r["source_id"] for r in labels])
    if args.calls == "whisper":  # no speaker labels: one mixed track
        src = {i: (c, audio[i], ts) for i, (c, _, ts) in src.items()}
    redactor = PresidioRedactor()
    model = os.environ.get("KEPT_TEXT_LLM_MODEL", "llamacpp/qwen3.8-27b")
    extractor = LLMExtractor(LiteLLMGateway(model=model, audit_log=DuckDBAuditLog(), timeout_s=120))

    t0 = time.time()
    redacted = {i: redactor.redact(t) for i, (_, t, _) in src.items()}  # spaCy: one thread

    def one(i: str) -> tuple[str, TextExtraction | str]:
        case_id, _, written_at = src[i]
        try:
            return i, extractor.extract(redacted[i], source_id=i, case_id=case_id, written_at=written_at)
        except Exception as e:  # a bad reply counts as a miss; keep going
            return i, f"{type(e).__name__}: {e}"

    with ThreadPoolExecutor(args.workers) as pool:
        results = dict(pool.map(one, list(src)))
    preds = {i: x for i, x in results.items() if isinstance(x, TextExtraction)}
    errors = {i: x for i, x in results.items() if isinstance(x, str)}

    split = f"calls-{args.calls}" if args.calls else args.split
    out = DATA / f"labels/runs/{PROMPT_VERSION}_{args.source}_{split}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as f:
        for i, x in results.items():
            row = {"source_id": i, "text": redacted[i].text}
            row |= {"error": x} if isinstance(x, str) else {"pred": x.model_dump(mode="json")}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(
        f"{model} {PROMPT_VERSION} {args.source}/{split}: {len(preds)} ok, {len(errors)} errors, "
        f"{time.time() - t0:.0f}s -> {out}"
    )
    for g in gate_report(preds, labels):
        print(
            f"  {g.feature:<20} f1 {g.f1:.3f}  p {g.precision:.3f}  r {g.recall:.3f}  "
            f"{'PASS' if g.passed else 'FAIL'}  {'' if g.passed else g.reason}"
        )


if __name__ == "__main__":
    main()
