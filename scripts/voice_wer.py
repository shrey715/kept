# ruff: noqa: E501  (report prose)
"""Voice: Whisper (local, GPU) on the 2,000 call recordings, scored against the release's transcripts.

    uv run python scripts/voice_wer.py                  # transcribes what isn't done yet, then writes the report
    uv run python scripts/voice_wer.py --report-only

Writes data/exports/voice/whisper.parquet (one row per recording) and docs/reports/voice_wer.md. Audio is mixed to
mono and resampled to 16 kHz; the model is openai/whisper-large-v3-turbo, already in the local Hugging Face cache.
WER is word-level edit distance over the reference word count, after lower-casing and dropping punctuation; the
reference's [PII] placeholders read as "redacted", which is what the synthetic voices say. Accent and noise columns are used only to check the transcriber works equally well for
everyone, never as inputs to a decision.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
VOICE = Path("/home/akshat/hackathons/maple_data/maple_collections_voice/files")
RAW = REPO / "data" / "raw"
OUT = REPO / "data" / "exports" / "voice" / "whisper.parquet"
REPORT = REPO / "docs" / "reports" / "voice_wer.md"
MODEL = "openai/whisper-large-v3-turbo"


def words(text: str) -> list[str]:
    text = re.sub(r"\[(pii|pci)\]", " redacted ", text.lower())  # the synthetic voices say "redacted" there
    return re.findall(r"[a-zà-ÿ0-9']+", text)


def wer(ref: list[str], hyp: list[str]) -> float:
    """Word edit distance / reference length (substitutions, insertions and deletions cost 1)."""
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i]
        for j, h in enumerate(hyp, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h)))
        prev = cur
    return prev[-1] / max(len(ref), 1)


def collapse_loops(text: str) -> str:
    """Whisper hallucinates a looping phrase over hold music and dead air ("We'll be right back." x40): keep the
    first of any sentence repeated back to back."""
    out: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
        if not out or sentence.lower() != out[-1].lower():
            out.append(sentence)
    return " ".join(out)


def load(path: Path) -> np.ndarray:
    from scipy.io import wavfile
    from scipy.signal import resample_poly

    rate, x = wavfile.read(path)
    x = x.astype(np.float32) / 32768.0
    if x.ndim == 2:  # agent left, customer right: one mixed track
        x = x.mean(axis=1)
    return resample_poly(x, 16000, rate).astype(np.float32) if rate != 16000 else x


def transcribe(samples: pd.DataFrame) -> None:
    import torch
    from transformers import pipeline

    if not torch.cuda.is_available():
        raise SystemExit("no CUDA: run this on the GPU machine")
    done = (
        pd.read_parquet(OUT) if OUT.exists() else pd.DataFrame(columns=["voice_sample_id", "text", "seconds"])
    )
    todo = samples[~samples.voice_sample_id.isin(done.voice_sample_id)]
    print(f"{len(done)} done, {len(todo)} to go", flush=True)
    asr = pipeline("automatic-speech-recognition", model=MODEL, device=0, dtype=torch.float16)
    rows = []
    for k, r in enumerate(todo.itertuples(), 1):
        t = time.perf_counter()
        out = asr(
            {"raw": load(VOICE / r.file_path), "sampling_rate": 16000}, chunk_length_s=30, batch_size=16
        )
        rows.append(
            {
                "voice_sample_id": r.voice_sample_id,
                "text": collapse_loops(out["text"]),
                "raw": out["text"].strip(),
                "seconds": time.perf_counter() - t,
            }
        )
        if k % 50 == 0 or k == len(todo):  # save as we go: a crash loses at most 50
            done = pd.concat([d for d in (done, pd.DataFrame(rows)) if len(d)], ignore_index=True)
            rows = []
            OUT.parent.mkdir(parents=True, exist_ok=True)
            done.to_parquet(OUT, index=False)
            print(f"{len(done)}/{len(samples)}", flush=True)


def reference(file_path: str) -> str:
    turns = json.loads((RAW / "files" / file_path).read_text())["turns"]
    return " ".join(t["text"] for t in turns)


def report(samples: pd.DataFrame) -> None:
    saved = pd.read_parquet(OUT)
    if "raw" not in saved:  # transcribed before collapse_loops existed
        saved = saved.assign(raw=saved.text, text=saved.text.map(collapse_loops))
        saved.to_parquet(OUT, index=False)
    w = saved.merge(samples, on="voice_sample_id")
    looped = int((saved.text != saved.raw).sum())
    w["ref"] = w.transcript_path.map(reference)
    w["wer"] = [wer(words(a), words(b)) for a, b in zip(w.ref, w.text, strict=True)]
    w["quality"] = np.where(w.sample_rate_hz == 8000, "8 kHz phone line (G.711)", "16 kHz wideband")

    def table(by: str, label: str) -> str:
        g = (
            w.groupby(by)
            .agg(calls=("wer", "size"), wer=("wer", "mean"), bank=("bank_wer", "mean"))
            .sort_values("calls", ascending=False)
        )
        return "\n".join(
            [f"| {label} | Calls | Whisper WER | Bank ASR's own WER estimate |", "|---|---:|---:|---:|"]
            + [
                f"| {k} | {int(r.calls):,} | {100 * r.wer:.1f}% | {100 * r.bank:.1f}% |"
                for k, r in g.iterrows()
            ]
        )

    hours = w.duration_sec.sum() / 3600
    speed = w.duration_sec.sum() / w.seconds.sum()
    REPORT.write_text(f"""# Voice: Whisper on the call recordings

Generated by `scripts/voice_wer.py`. {len(w):,} recordings ({hours:.0f} hours of audio), transcribed locally on one
RTX 5070 Ti with `{MODEL}` at {speed:.0f}× real time. Nothing leaves the machine.

## Accuracy

**Word error rate: {100 * w.wer.mean():.1f}% on average, median {100 * w.wer.median():.1f}%**, against the release's
transcripts. For scale, the bank's own speech-to-text estimates {100 * w.bank_wer.mean():.1f}% for the same calls.
Over hold music and dead air Whisper can loop a phrase ("We'll be right back." again and again); a sentence repeated
back to back is kept once, which changed {looped:,} of the {len(saved):,} transcripts.

{table("quality", "Audio")}

{table("background_noise_type", "Background noise")}

## Does it work equally well for every caller?

Accent is never a model input (it's a protected-attribute proxy in our contract). We only use it here to check that
the transcriber doesn't serve some customers worse than others, because a hardship phrase it mishears is a hardship
flag the customer doesn't get.

{table("customer_accent_region", "Customer's accent region")}

## How it's used

The transcript goes through the same path as a typed note: redaction first, then the local extraction model, so a
call can raise a hardship flag with the exact words it relied on. Voice biometrics, pitch and accent are never used.

## Limits

- Mono mix: the agent and customer channels are mixed, so the transcript has no speaker labels. Transcribing the two
  channels separately (they're on separate stereo channels in {100 * (w.channels == 2).mean():.0f}% of calls) would give them.
- The reference transcripts are the scripts these synthetic calls were voiced from, so WER here is cleaner than it
  would be against human-checked transcripts of real calls.
""")
    print(f"wrote {REPORT}; mean WER {100 * w.wer.mean():.1f}%")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report-only", action="store_true")
    ap.add_argument("--limit", type=int, help="first N recordings (a quick check)")
    a = ap.parse_args()
    samples = duckdb.sql(f"""
        select v.voice_sample_id, v.file_path, v.sample_rate_hz, v.channels, v.duration_sec, v.background_noise_type,
               v.customer_accent_region, t.file_path as transcript_path, t.wer_estimate as bank_wer
        from read_csv('{RAW / "voice_samples.csv"}', header=true) v
        join read_csv('{RAW / "call_transcripts.csv"}', header=true) t using (voice_sample_id)
        order by v.voice_sample_id""").df()
    if a.limit:
        samples = samples.head(a.limit)
    if not a.report_only:
        transcribe(samples)
    report(samples)


if __name__ == "__main__":
    assert wer(["a", "b", "c"], ["a", "x", "c", "d"]) == 2 / 3  # one substitution, one insertion
    assert words("Sure, it's [PII]. $450!") == ["sure", "it's", "redacted", "450"]
    assert (
        collapse_loops("Okay. We'll be right back. We'll be right back. Bye.")
        == "Okay. We'll be right back. Bye."
    )
    main()
