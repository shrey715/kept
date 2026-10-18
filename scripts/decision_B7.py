# ruff: noqa: E501
"""Decision B7: keyword rules vs SetFit vs the LLM for reading notes. One holdout (the 149 public-labelled notes the
prompt was never tuned on, `kept.text.labels.is_holdout`), one metric (F1, recall, precision of the positive class from
`kept.text.evaluate`), one machine. Texts are the stored redacted notes, which is what the LLM and SetFit both read.

    uv run python scripts/decision_B7.py cpu      # keyword baseline, SetFit accuracy, SetFit CPU speed  (no LLM, no GPU)
    uv run python scripts/decision_B7.py gpu      # SetFit GPU speed + all 760,594 notes; the LLM on 200 notes, 2 slots (`make llm` first)
    uv run python scripts/decision_B7.py report   # merge -> data/exports/reports/decision_B7.json, docs/reports/figures/dec_B7.png

SetFit predicts hardship only (kept.text.backfill), so promise-to-pay is compared for keywords and the LLM alone.
The LLM's accuracy is not rerun: it is read from the predictions stored by scripts/eval_extraction.py (extraction_gate.md).
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("KEPT_DATA_DIR", REPO / "data"))
REPORTS = DATA / "exports" / "reports"
PART = REPORTS / "decision_B7_parts"
NOTES_PARQUET = sorted((DATA / "exports" / "redacted_notes").glob("redacted_notes_*.parquet"))[-1]
LABELS = DATA / "labels" / "agent_notes_labels_public_500.csv"
LLM_PREDS = DATA / "labels" / "runs" / "extract-v4_notes_holdout.jsonl"
SETFIT = sorted((DATA / "models" / "setfit").glob("setfit-v1_*"))[-1]
N_NOTES = 760_594
TRAINING_LABELS = 1_604  # docs/team/tracks/Track_C.md: SetFit's training set

# What a collections team writes in an afternoon: the phrases agents use when a customer is in trouble or promises to pay.
HARDSHIP = re.compile(
    r"laid off|lay ?off|lost (?:his |her |their |my )?job|job loss|unemploy|\bEI\b|employment insurance|"
    r"hours? (?:cut|reduced)|reduced hours|shifts? cut|pay cut|medical|sick|ill(?:ness)?\b|surgery|hospital|disab|"
    r"cancer|funeral|passed away|death|bereave|divorc|separat|hardship|can'?t afford|cannot afford|struggl|"
    r"evacuat|wildfire|flood|"
    r"mis à pied|perdu son emploi|perte d'emploi|chômage|assurance[- ]emploi|heures (?:coupées|réduites)|malad|"
    r"hôpital|décès|deuil|divorce|séparation|difficultés? financi|ne peut pas payer",
    re.I,
)
PROMISE = re.compile(
    r"promis|will pay|\bptp\b|can only pay|agreed to pay|pay(?:ing)? (?:on|by|\$)|\$\s?\d|"
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]* \d{1,2}\b|\b\d{1,2}(?:st|nd|rd|th)\b|"
    r"\b\d{1,2}/\d{1,2}\b|next (?:week|friday|monday|payday)|on payday|"
    r"va payer|payera|a promis|peut seulement payer|paiement (?:le|prévu)|\d{1,2} (?:janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)",
    re.I,
)


def metrics(y_true: list[bool], y_pred: list[bool]) -> dict[str, float | int]:
    from kept.text.evaluate import binary_metrics

    p, r, f = binary_metrics(y_true, y_pred)
    return {"f1": round(f, 3), "recall": round(r, 3), "precision": round(p, 3), "n": len(y_true), "positives": sum(y_true)}


def holdout() -> tuple[list[str], list[str], dict[str, list[bool]]]:
    """Ids, redacted texts and the binarised gold (hardship = possible or clear, promise = mentioned) of the holdout."""
    from kept.contracts import HardshipSignal
    from kept.text.labels import load_labels

    rows = [r for r in load_labels(LABELS) if r["holdout"]]
    ids = [r["source_id"] for r in rows]
    text = dict(duckdb.execute("select source_id, text from read_parquet(?) where source_id in ?", [str(NOTES_PARQUET), ids]).fetchall())
    gold = {
        "hardship": [r["hardship_signal"] is not HardshipSignal.NONE for r in rows],
        "promise": [bool(r["promise_intent"]) for r in rows],
    }
    return ids, [text[i] for i in ids], gold


def put(name: str, value: object) -> None:
    PART.mkdir(parents=True, exist_ok=True)
    (PART / f"{name}.json").write_text(json.dumps(value, indent=1))
    print(name, json.dumps(value)[:400], flush=True)


def bench(fn, texts: list[str], repeats: int = 3) -> dict[str, float]:
    """Seconds per 1,000 notes: the best of `repeats` after one warm-up pass."""
    fn(texts[:64])
    best = min(_timed(fn, texts) for _ in range(repeats))
    return {"s_per_1000": round(best / len(texts) * 1000, 3), "notes": len(texts)}


def _timed(fn, texts: list[str]) -> float:
    t = time.perf_counter()
    fn(texts)
    return time.perf_counter() - t


def sample_notes(n: int) -> list[str]:
    return [t for (t,) in duckdb.execute(f"select text from read_parquet(?) where source_type='note' using sample reservoir({int(n)} rows) repeatable (7)", [str(NOTES_PARQUET)]).fetchall()]


def cpu() -> None:
    _, texts, gold = holdout()
    kw = {"hardship": [bool(HARDSHIP.search(t)) for t in texts], "promise": [bool(PROMISE.search(t)) for t in texts]}
    t = time.perf_counter()
    for _ in range(100):
        [HARDSHIP.search(x) and PROMISE.search(x) for x in texts]
    kw_rate = (time.perf_counter() - t) / (100 * len(texts)) * 1000
    put("keywords", {"hardship": metrics(gold["hardship"], kw["hardship"]), "promise": metrics(gold["promise"], kw["promise"]), "s_per_1000": round(kw_rate, 5)})

    import torch

    from kept.contracts import HardshipSignal
    from kept.text.backfill import SetFitBackfill

    torch.set_num_threads(4)
    sf = SetFitBackfill.load(SETFIT)
    sf._model.to("cpu")

    def run(xs: list[str]):
        return sf._model.predict_proba(xs, batch_size=64, as_numpy=True)

    proba = run(texts)
    classes = list(sf._model.model_head.classes_)
    pred = [HardshipSignal(classes[r.argmax()]) is not HardshipSignal.NONE for r in proba]
    put("setfit_accuracy", {"hardship": metrics(gold["hardship"], pred), "model": SETFIT.name})
    sample = sample_notes(1000)
    put("setfit_cpu", {**bench(run, sample), "threads": 4, "batch_size": 64, "cpu_count": os.cpu_count()})


def gpu() -> None:
    import torch

    from kept.text.backfill import SetFitBackfill

    assert torch.cuda.is_available(), "CUDA is not available"
    sf = SetFitBackfill.load(SETFIT)
    sf._model.to("cuda")

    def run(xs: list[str]):
        return sf._model.predict_proba(xs, batch_size=256, as_numpy=True)

    put("setfit_gpu", {**bench(run, sample_notes(1000)), "batch_size": 256, "device": torch.cuda.get_device_name(0)})

    # every note, in chunks, stopping at 30 minutes (then the measured rate times the count is reported, and says so)
    limit_s, done, t0 = 1800, 0, time.perf_counter()
    con = duckdb.connect()
    con.execute("set memory_limit='3GB'")
    cur = con.execute("select text from read_parquet(?) where source_type='note'", [str(NOTES_PARQUET)])
    while chunk := cur.fetchmany(20_000):
        run([r[0] or "" for r in chunk])
        done += len(chunk)
        if time.perf_counter() - t0 > limit_s:
            break
    sec = time.perf_counter() - t0
    put(
        "setfit_all_notes",
        {"notes_done": done, "notes_total": N_NOTES, "seconds": round(sec, 1), "complete": done >= N_NOTES, "total_seconds": round(sec * N_NOTES / done, 1)},
    )

    llm()


def llm() -> None:
    """The live extractor (same class, prompt and 2 slots the product uses) on 200 public-labelled notes: the 149 holdout
    plus the first 51 others. Wall-clock for the batch, 2 requests in flight. No cache: every note is a new text."""
    from concurrent.futures import ThreadPoolExecutor

    from kept.common.audit import DuckDBAuditLog
    from kept.common.llm import LiteLLMGateway
    from kept.text.extract import LLMExtractor
    from kept.text.labels import load_labels
    from kept.text.redact import stored_redacted

    labels = load_labels(LABELS)
    ids = [r["source_id"] for r in labels if r["holdout"]] + [r["source_id"] for r in labels if not r["holdout"]][:51]
    q = duckdb.execute(
        "select n.note_id, n.case_id, n.note_ts, r.text from read_csv(?, all_varchar=true) n join read_parquet(?) r on r.source_id = n.note_id where n.note_id in ?",
        [str(DATA / "raw" / "agent_notes.csv"), str(NOTES_PARQUET), ids],
    ).fetchall()
    ex = LLMExtractor(LiteLLMGateway(model=os.environ.get("KEPT_TEXT_LLM_MODEL", "llamacpp/qwen3.8-27b"), audit_log=DuckDBAuditLog(), timeout_s=120))

    def one(row: tuple[str, str, str, str]) -> float:
        t = time.perf_counter()
        with contextlib.suppress(ValueError):  # a reply off the schema: still the time it took
            ex.extract(stored_redacted(row[3], "presidio-v5"), source_id=row[0], case_id=row[1], written_at=datetime.fromisoformat(row[2]))
        return time.perf_counter() - t

    t0 = time.perf_counter()
    with ThreadPoolExecutor(2) as pool:
        lat = list(pool.map(one, q))
    wall = time.perf_counter() - t0
    put(
        "llm_speed",
        {
            "notes": len(q),
            "slots": 2,
            "wall_s": round(wall, 1),
            "s_per_note": round(wall / len(q), 2),
            "s_per_1000": round(wall / len(q) * 1000, 1),
            "median_latency_s": round(statistics.median(lat), 2),
            "note": "other jobs shared the CPU; llama-server on the GPU was otherwise idle",
        },
    )


def report() -> None:
    P = {p.stem: json.loads(p.read_text()) for p in PART.glob("*.json")}
    ids, _, gold = holdout()
    from kept.contracts import TextExtraction
    from kept.text.labels import gate_report, load_labels

    preds = {}
    for line in LLM_PREDS.read_text().splitlines():
        r = json.loads(line)
        if "pred" in r:
            preds[r["source_id"]] = TextExtraction.model_validate(r["pred"])
    gates = {g.feature: g for g in gate_report(preds, [r for r in load_labels(LABELS) if r["holdout"]])}
    llm_acc = {k: {"f1": round(gates[f].f1, 3), "recall": round(gates[f].recall, 3), "precision": round(gates[f].precision, 3), "n": gates[f].n} for k, f in (("hardship", "hardship_signal"), ("promise", "promise_intent"))}

    llm_s = P["llm_speed"]["s_per_1000"]
    sf_all = P["setfit_all_notes"]
    # ponytail: label cost from the measured Qwen rate; the 1,604 labels were made on 3 Oct with Gemma 3 12B on Ollama, whose time wasn't logged (no audit rows for that run)
    out = {
        "holdout": {"notes": len(ids), "hardship_positives": sum(gold["hardship"]), "promise_positives": sum(gold["promise"])},
        "accuracy": {"keywords": {k: P["keywords"][k] for k in ("hardship", "promise")}, "setfit": {"hardship": P["setfit_accuracy"]["hardship"]}, "llm": llm_acc},
        "speed_s_per_1000": {"keywords": P["keywords"]["s_per_1000"], "setfit_cpu": P["setfit_cpu"]["s_per_1000"], "setfit_gpu": P["setfit_gpu"]["s_per_1000"], "llm_2_slots": llm_s},
        "hours_to_label_all_760594": {
            "keywords": round(P["keywords"]["s_per_1000"] * N_NOTES / 1000 / 3600, 4),
            "setfit_gpu": round(sf_all["total_seconds"] / 3600, 3),
            "setfit_gpu_measured_over_all_notes": sf_all["complete"],
            "setfit_cpu_extrapolated": round(P["setfit_cpu"]["s_per_1000"] * N_NOTES / 1000 / 3600, 2),
            "llm_extrapolated": round(llm_s * N_NOTES / 1000 / 3600, 1),
            "llm_days_extrapolated": round(llm_s * N_NOTES / 1000 / 86400, 1),
        },
        "llm_hours_for_training_labels": {"labels": TRAINING_LABELS, "hours": round(llm_s * TRAINING_LABELS / 1000 / 3600, 2), "basis": "measured Qwen rate x 1,604 (original run's time was not logged)"},
        "parts": P,
    }
    (REPORTS / "decision_B7.json").write_text(json.dumps(out, indent=1))

    sys.path.insert(0, str(REPO / "scripts"))
    from reportlib import BLUE, INK, KEPT, ORANGE, plt, save, style, tidy

    style()
    fig, ax = plt.subplots(figsize=(7, 4))
    h = out["hours_to_label_all_760594"]
    pts = [
        ("Keyword rules", h["keywords"], out["accuracy"]["keywords"]["hardship"]["f1"], ORANGE),
        ("SetFit (GPU)", h["setfit_gpu"], out["accuracy"]["setfit"]["hardship"]["f1"], KEPT),
        ("LLM (2 slots)", h["llm_extrapolated"], llm_acc["hardship"]["f1"], BLUE),
    ]
    for name, x, y, c in pts:
        ax.scatter(x, y, s=90, color=c, zorder=3)
        ax.annotate(f"{name}\nF1 {y:.2f}, {x:.3g} h", (x, y), textcoords="offset points", xytext=(8, -22), fontsize=8, color=INK)
    ax.set_xscale("log")
    ax.set_xlim(min(p[1] for p in pts) / 4, max(p[1] for p in pts) * 6)
    ax.set_ylim(0.5, 1.0)
    ax.set_xlabel("hours to label all 760,594 notes (log scale; LLM extrapolated from a measured rate)")
    ax.set_ylabel("hardship F1 on the 149-note holdout")
    ax.set_title("Accuracy against time to read the whole history", loc="left")
    tidy(ax)
    print(save(fig, "dec_B7"))
    print(json.dumps({k: v for k, v in out.items() if k != "parts"}, indent=1))


if __name__ == "__main__":
    {"cpu": cpu, "gpu": gpu, "llm": llm, "report": report}[sys.argv[1]]()
