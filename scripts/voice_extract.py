# ruff: noqa: E501  (SQL)
"""Read the recorded calls on tonight's open cases from Whisper's own transcript (scripts/voice_wer.py):
redaction, then the local extraction model, as for a typed note. For the case page's Calls panel only.

    uv run python scripts/voice_extract.py          # resumes; ~4 s a call on the GPU

Writes data/exports/voice/voice_extractions.parquet. Display only: the card already reads the same call from the
release's transcript (text.extractions), so feeding these in too would count every call twice.
"""

from __future__ import annotations

import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd

from kept.common.audit import DuckDBAuditLog
from kept.common.llm import LiteLLMGateway
from kept.config import WAREHOUSE_PATH
from kept.text.extract import LLMExtractor
from kept.text.live import DEFAULT_MODEL
from kept.text.redact import PresidioRedactor

REPO = Path(__file__).resolve().parents[1]
VOICE = REPO / "data" / "exports" / "voice"
OUT = VOICE / "voice_extractions.parquet"


def main() -> None:
    warnings.filterwarnings("ignore")
    with duckdb.connect(str(WAREHOUSE_PATH), read_only=True) as con:  # closed before the long part
        calls = con.execute(
            f"""select v.voice_sample_id, t.case_id, t.call_start_ts::timestamp as call_start, v.duration_sec, w.text
                from read_csv('{REPO / "data/raw/voice_samples.csv"}', header=true) v
                join read_csv('{REPO / "data/raw/call_transcripts.csv"}', header=true) t using (voice_sample_id)
                join read_parquet('{VOICE / "whisper.parquet"}') w using (voice_sample_id)
                where t.case_id in (select case_id from nba.cards)
                order by v.voice_sample_id"""
        ).df()
    done = pd.read_parquet(OUT) if OUT.exists() else pd.DataFrame(columns=["voice_sample_id"])
    todo = calls[~calls.voice_sample_id.isin(done.voice_sample_id)]
    print(f"{len(calls)} calls on open cases, {len(todo)} to read", flush=True)
    redactor = PresidioRedactor()
    extractor = LLMExtractor(LiteLLMGateway(model=DEFAULT_MODEL, audit_log=DuckDBAuditLog(), timeout_s=120))

    def one(r: pd.Series) -> dict[str, object]:
        text = redactor.redact(r.text)
        row: dict[str, object] = {**r.drop("text").to_dict(), "redacted_text": text.text}
        try:
            x = extractor.extract(
                text, source_id=r.voice_sample_id, case_id=r.case_id, written_at=r.call_start
            )
            row["extraction"] = x.model_dump_json()
        except Exception as e:  # a bad reply: the panel shows the transcript without signals
            row["extraction"] = None
            row["error"] = f"{type(e).__name__}: {e}"[:200]
        return row

    rows: list[dict[str, object]] = []
    t0 = time.time()
    with ThreadPoolExecutor(2) as pool:
        for k, row in enumerate(pool.map(one, (r for _, r in todo.iterrows())), 1):
            rows.append(row)
            if k % 50 == 0 or k == len(todo):  # save as we go
                done = pd.concat([d for d in (done, pd.DataFrame(rows)) if len(d)], ignore_index=True)
                rows = []
                done.to_parquet(OUT, index=False)
                print(f"{len(done)}/{len(calls)} ({time.time() - t0:.0f}s)", flush=True)


if __name__ == "__main__":
    print(datetime.now().isoformat(timespec="seconds"))
    main()
