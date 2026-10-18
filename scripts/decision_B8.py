# ruff: noqa: E501
"""Decision B8: which Whisper size for the call recordings. Same transcription settings, scoring and text clean-up as
scripts/voice_wer.py (imported, not copied), on a fixed stratified sample of 300 of the 2,000 recordings.

    .venv/bin/python scripts/decision_B8.py sample                      # fixed sample -> decision_B8/sample.csv
    .venv/bin/python scripts/decision_B8.py run openai/whisper-small     # one model per process -> decision_B8/<model>.parquet/.json
    .venv/bin/python scripts/decision_B8.py run MODEL --limit 3 --out smoke
    .venv/bin/python scripts/decision_B8.py report                       # -> decision_B8.json, docs/reports/figures/dec_B8.png

large-v3-turbo is not re-transcribed: its text and seconds come from data/exports/voice/whisper.parquet (the full
2,000-call run, on an otherwise idle GPU). Only its VRAM and load time can come from a short `run` (`--limit`).
Run under: systemd-run --user --scope -q -p MemoryMax=12G -p MemorySwapMax=0 -- env HF_HUB_OFFLINE=1 ...
"""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import threading
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import voice_wer as vw  # noqa: E402

REPORTS = REPO / "data" / "exports" / "reports"
OUTDIR = REPORTS / "decision_B8"
TURBO = "openai/whisper-large-v3-turbo"
MODELS = ["openai/whisper-small", "distil-whisper/distil-large-v3", "openai/whisper-large-v3", TURBO]
N, MIN_CELL, SEED = 300, 10, "b8"


def samples() -> pd.DataFrame:
    """The frame voice_wer.main builds, all 2,000 recordings."""
    return duckdb.sql(f"""
        select v.voice_sample_id, v.file_path, v.sample_rate_hz, v.channels, v.duration_sec, v.background_noise_type,
               v.customer_accent_region, v.language, t.file_path as transcript_path, t.wer_estimate as bank_wer
        from read_csv('{vw.RAW / "voice_samples.csv"}', header=true) v
        join read_csv('{vw.RAW / "call_transcripts.csv"}', header=true) t using (voice_sample_id)
        order by v.voice_sample_id""").df()


def sample() -> None:
    """300 recordings, proportional to language x sample rate x noise (largest remainder), seed "b8"."""
    s = samples()
    keys = ["language", "sample_rate_hz", "background_noise_type"]
    size = s.groupby(keys).size()
    quota = size * N / len(s)
    alloc = quota.astype(int)
    alloc[(quota - alloc).sort_values(ascending=False).index[: N - alloc.sum()]] += 1
    rng = random.Random(SEED)
    ids: list[str] = []
    for key, g in s.groupby(keys):
        ids += rng.sample(sorted(g.voice_sample_id), int(alloc[key]))
    pick = s[s.voice_sample_id.isin(ids)].sort_values("voice_sample_id")
    cells = pick.groupby(["language", "sample_rate_hz"]).size()
    assert len(pick) == N and cells.min() >= MIN_CELL, cells  # ponytail: asserts the floor instead of rebalancing; holds on this data
    OUTDIR.mkdir(parents=True, exist_ok=True)
    pick[["voice_sample_id"]].to_csv(OUTDIR / "sample.csv", index=False)
    print(pick.groupby(keys).size().to_string())


def sample_frame() -> pd.DataFrame:
    ids = pd.read_csv(OUTDIR / "sample.csv").voice_sample_id
    return samples().merge(ids.to_frame(), on="voice_sample_id")


def stem(model: str) -> str:
    return model.split("/")[-1]


def snapshot_bytes(model: str) -> int:
    from huggingface_hub import snapshot_download

    p = Path(snapshot_download(model, allow_patterns=["model.safetensors"], local_files_only=True)) / "model.safetensors"
    return p.resolve().stat().st_size


def run(model: str, limit: int | None, out: str, batch: int = 16) -> None:
    import torch
    from transformers import pipeline

    if not torch.cuda.is_available():
        raise SystemExit("no CUDA: run this on the GPU machine")
    if model == TURBO and not limit:
        raise SystemExit("turbo is taken from data/exports/voice/whisper.parquet; use --limit for a VRAM check only")
    d = REPORTS / out
    d.mkdir(parents=True, exist_ok=True)
    f = sample_frame()
    if limit:
        f = f.head(limit)
    path = d / f"{stem(model)}.parquet"
    done = pd.read_parquet(path) if path.exists() else pd.DataFrame()
    todo = f[~f.voice_sample_id.isin(done.get("voice_sample_id", []))]
    print(f"{model}: {len(done)} done, {len(todo)} to go", flush=True)

    peak_smi = [0]
    stop = threading.Event()

    def poll() -> None:  # this process's GPU memory as nvidia-smi sees it (the other llama-server is a different pid)
        while not stop.is_set():
            o = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"], capture_output=True, text=True).stdout
            for line in o.splitlines():
                pid, mb = (x.strip() for x in line.split(","))
                if int(pid) == os.getpid():
                    peak_smi[0] = max(peak_smi[0], int(mb))
            stop.wait(0.5)

    threading.Thread(target=poll, daemon=True).start()
    torch.cuda.reset_peak_memory_stats()
    t0 = time.perf_counter()
    asr = pipeline("automatic-speech-recognition", model=model, device=0, dtype=torch.float16)
    load_s = time.perf_counter() - t0
    rows: list[dict] = []
    for k, r in enumerate(todo.itertuples(), 1):
        audio = vw.load(vw.VOICE / r.file_path)
        t = time.perf_counter()
        o = asr({"raw": audio, "sampling_rate": 16000}, chunk_length_s=30, batch_size=batch)
        rows.append(
            {
                "voice_sample_id": r.voice_sample_id,
                "text": vw.collapse_loops(o["text"]),
                "raw": o["text"].strip(),
                "seconds": time.perf_counter() - t,
                "audio_seconds": len(audio) / 16000,
            }
        )
        if k % 25 == 0 or k == len(todo):  # save as we go
            done = pd.concat([x for x in (done, pd.DataFrame(rows)) if len(x)], ignore_index=True)
            rows = []
            done.to_parquet(path, index=False)
            print(f"{len(done)}/{len(f)}", flush=True)
    stop.set()
    meta = {
        "model": model,
        "calls": len(done),
        "load_seconds": round(load_s, 2),
        "peak_vram_allocated_mb": round(torch.cuda.max_memory_allocated() / 2**20),
        "peak_vram_nvidia_smi_mb": peak_smi[0],
        "batch_size": batch,
        "model_file_mb": round(snapshot_bytes(model) / 2**20),
        "torch": torch.__version__,
    }
    (d / f"{stem(model)}.json").write_text(json.dumps(meta, indent=1))
    print(meta)


def score(w: pd.DataFrame) -> pd.DataFrame:
    w = w.copy()
    w["ref"] = w.transcript_path.map(vw.reference)
    w["wer"] = [vw.wer(vw.words(a), vw.words(b)) for a, b in zip(w.ref, w.text, strict=True)]
    return w


def by(w: pd.DataFrame, col: str) -> dict:
    return {str(k): {"calls": len(g), "wer": round(float(g.wer.mean()), 4)} for k, g in w.groupby(col)}


def report() -> None:
    f = sample_frame()
    ids = set(f.voice_sample_id)
    per: dict[str, pd.DataFrame] = {}
    meta: dict[str, dict] = {}
    for m in MODELS:
        if m == TURBO:  # text and seconds from the full 2,000-call run
            t = pd.read_parquet(vw.OUT)
            t = t[t.voice_sample_id.isin(ids)]
            vm = REPORTS / "smoke" / f"{stem(m)}.json"  # VRAM / load time from a short `run --limit 20 --out smoke`
            meta[m] = {k: v for k, v in json.loads(vm.read_text()).items() if k != "calls"} if vm.exists() else {}
            meta[m]["model_file_mb"] = round(snapshot_bytes(m) / 2**20)
        else:
            p = OUTDIR / f"{stem(m)}.parquet"
            if not p.exists():
                continue
            t = pd.read_parquet(p)
            meta[m] = json.loads((OUTDIR / f"{stem(m)}.json").read_text())
        assert set(t.voice_sample_id) == ids, (m, len(t))
        per[m] = score(f.merge(t[["voice_sample_id", "text", "raw", "seconds"]], on="voice_sample_id"))
    base = per[TURBO].set_index("voice_sample_id").wer
    rng = np.random.default_rng(8)
    out: dict = {"calls": len(f), "seed": SEED, "sample_composition": {
        "sample_rate_hz": {str(k): int(v) for k, v in f.sample_rate_hz.value_counts().items()},
        "noise": {k: int(v) for k, v in f.background_noise_type.value_counts().items()},
        "language": {k: int(v) for k, v in f.language.value_counts().items()},
        "audio_hours": round(f.duration_sec.sum() / 3600, 2)}, "models": {}}
    for m, w in per.items():
        d = (w.set_index("voice_sample_id").wer - base).to_numpy()
        boot = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(2000)]
        out["models"][m] = {
            "wer": round(float(w.wer.mean()), 4),
            "wer_median": round(float(w.wer.median()), 4),
            "by_language": by(w, "language"),
            "by_sample_rate": by(w, "sample_rate_hz"),
            "by_noise": by(w, "background_noise_type"),
            "looped_share": round(float((w.text != w.raw).mean()), 4),
            "real_time_factor": round(float(w.duration_sec.sum() / w.seconds.sum()), 1),
            "wer_minus_turbo": round(float(d.mean()), 4),
            "wer_minus_turbo_ci95": [round(float(np.percentile(boot, 2.5)), 4), round(float(np.percentile(boot, 97.5)), 4)],
            **meta[m],
        }
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "decision_B8.json").write_text(json.dumps(out, indent=1))

    from reportlib import BLUE, INK, KEPT, ORANGE, plt, save, style, tidy

    style()
    fig, ax = plt.subplots(figsize=(7, 4))
    for (m, v), c in zip(out["models"].items(), [ORANGE, BLUE, INK, KEPT], strict=False):
        ax.scatter(v["real_time_factor"], 100 * v["wer"], s=90, color=c, zorder=3)
        ax.annotate(f"{stem(m)}\nWER {100 * v['wer']:.1f}%, {v['real_time_factor']:.0f}x", (v["real_time_factor"], 100 * v["wer"]), textcoords="offset points", xytext=(8, -22), fontsize=8, color=INK)
    ax.set_xscale("log")
    ax.set_xlim(14, 400)
    ax.set_ylim(6, 22)
    ax.set_xticks([20, 50, 100, 200], ["20x", "50x", "100x", "200x"])
    ax.minorticks_off()
    ax.set_xlabel("speed, audio seconds per transcription second (log scale)")
    ax.set_ylabel("word error rate, % (300 calls)")
    ax.set_title("Word error against speed, by Whisper size", loc="left")
    tidy(ax)
    print(save(fig, "dec_B8"))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["sample", "run", "report"])
    ap.add_argument("model", nargs="?")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--batch", type=int, default=16, help="pipeline batch_size (large-v3 does not fit at 16 on 16 GB)")
    ap.add_argument("--out", default="decision_B8", help="dir under data/exports/reports/ (smoke tests: smoke)")
    a = ap.parse_args()
    {"sample": sample, "report": report}.get(a.cmd, lambda: run(a.model, a.limit, a.out, a.batch))()
