# ruff: noqa: E501
"""Decision B1: which local LLM. The three jobs (the Ask, text extraction, case briefs) on four models, one at a time on
the 16 GB GPU, all served by scripts/llm_server.sh (two 16k slots, 8-bit KV cache, thinking off, -ngl 99):

    live      Qwen3.8-27B UD-Q3_K_XL (the product)
    qwen3-14b Qwen3-14B Q4_K_M            qwen3-8b Qwen3-8B Q4_K_M            gemma3-12b Gemma 3 12B it Q4_K_M

    uv run python scripts/decision_B1.py run MODEL [--steps speed,asks,extract,briefs]   # starts and stops llama-server
    uv run python scripts/decision_B1.py report                                          # -> decision_B1.json, dec_B1.png

asks     the three Ask suites through `kept serve` (scripts/decision_B5.py run_suites, graded as ask_accuracy.md).
         The live model's suites are the B5 "live" run of the same day and are not repeated.
extract  scripts/eval_extraction.py on the notes and transcripts holdouts (149 each): F1 and recall per field, replies
         that failed the schema, latency per call from the audit log. The live model's numbers are read from
         docs/reports/extraction_gate.md.
briefs   50 case briefs (every 10th case of /queue's top 500). Their numbered sources come from `kept serve`; each model
         then writes the bullets and kept.app.briefs.check's rules are applied bullet by bullet: a bullet with no real
         cite, or with a number its cited sources lack, is dropped; the numbers counted are those removed.
speed    six one-request-at-a-time generations: prompt and generation tokens per second as llama-server reports them.
VRAM is sampled from nvidia-smi once a second for the whole run of that model (KV cache is allocated when the model loads).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import signal
import statistics
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import decision_B5 as b5  # noqa: E402

DATA = b5.DATA
REPORTS = b5.REPORTS
OUT = REPORTS / "decision_B1"
HOME = Path.home()
LLM = "http://127.0.0.1:8081"
VENV_BIN = Path(sys.executable).parent
SCOPE = "systemd-run --user --scope -q -p MemoryMax={cap} -p MemorySwapMax=0 --"
SERVE = f"{SCOPE.format(cap='7G')} {VENV_BIN}/kept serve --port {{port}}"
FEATURES_AS_OF = "2026-10-15T07:00:00+00:00"  # an hour after the last nightly: later than a day, every card says "features are stale"
SERVE_AT = f"{SCOPE.format(cap='7G')} {sys.executable} {REPO}/scripts/decision_B1.py serve-at --port {{port}}"
MODELS = {
    "live": ("Qwen3.8-27B UD-Q3_K_XL", HOME / "models/Qwen3.8-27B-UD-Q3_K_XL.gguf", "Qwen3.8 licence per its card"),
    "qwen3-14b": ("Qwen3-14B Q4_K_M", HOME / "models/b1/Qwen3-14B-Q4_K_M.gguf", "Apache-2.0"),
    "qwen3-8b": ("Qwen3-8B Q4_K_M", HOME / "models/b1/Qwen3-8B-Q4_K_M.gguf", "Apache-2.0"),
    "gemma3-12b": ("Gemma 3 12B it Q4_K_M", HOME / "models/b1/gemma-3-12b-it-Q4_K_M.gguf", "Gemma terms of use"),
}
N_BRIEFS = 50
SPEED_PROMPT = "Write a detailed, numbered guide of twelve practical steps for a collections agent preparing to call a customer who has missed two payments. Explain each step in three sentences."


# ---------------------------------------------------------------- llama-server and VRAM
def vram_mib() -> int:
    out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], capture_output=True, text=True, check=True)
    return int(out.stdout.split()[0])


class Sampler(threading.Thread):
    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.peak, self.stop_ = 0, threading.Event()

    def run(self) -> None:
        while not self.stop_.wait(1):
            self.peak = max(self.peak, vram_mib())


class LlamaServer:
    """scripts/llm_server.sh with KEPT_LLM_GGUF set, in a 12 GB memory scope. Used as a context manager."""

    def __init__(self, gguf: Path, port: int = 8081, extra: str = "") -> None:
        self.gguf, self.port, self.extra = gguf, port, extra

    def __enter__(self) -> LlamaServer:
        self.base = vram_mib()
        env = {**os.environ, "KEPT_LLM_GGUF": str(self.gguf)}
        cmd = f"{SCOPE.format(cap='12G')} sh {REPO}/scripts/llm_server.sh {self.extra}"
        self.log = (OUT / f"server_{self.gguf.stem}.log").open("w")
        self.proc = subprocess.Popen(shlex.split(cmd), env=env, stdout=self.log, stderr=subprocess.STDOUT, start_new_session=True)
        t0 = time.time()
        while not b5._get(f"{LLM}/health"):
            if self.proc.poll() is not None or time.time() - t0 > 600:
                raise RuntimeError(f"llama-server didn't start: see {self.log.name}")
            time.sleep(2)
        self.load_s = round(time.time() - t0, 1)
        self.idle_mib = vram_mib()
        self.sampler = Sampler()
        self.sampler.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.sampler.stop_.set()
        os.killpg(self.proc.pid, signal.SIGTERM)
        try:
            self.proc.wait(60)
        except subprocess.TimeoutExpired:
            os.killpg(self.proc.pid, signal.SIGKILL)

    def vram(self) -> dict[str, int]:
        return {"baseline_mib": self.base, "idle_mib": self.idle_mib, "peak_mib": max(self.sampler.peak, self.idle_mib)}


def chat(body: dict[str, object], port: int = 8081, timeout: int = 600) -> dict[str, object]:
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions", json.dumps(body).encode(), {"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)  # type: ignore[no-any-return]


def p95(xs: list[float]) -> float:
    return round(statistics.quantiles(xs, n=20)[-1], 2) if len(xs) >= 2 else (xs[0] if xs else 0.0)


# ---------------------------------------------------------------- steps
def speed(tag: str) -> dict[str, object]:
    chat({"messages": [{"role": "user", "content": "hi"}], "max_tokens": 4})  # warm up
    rows = []
    for _ in range(6):
        t0 = time.time()
        r = chat({"messages": [{"role": "user", "content": SPEED_PROMPT}], "max_tokens": 256, "temperature": 0})
        t = r["timings"]  # type: ignore[index]
        rows.append({"prompt_tokens": t["prompt_n"], "gen_tokens": t["predicted_n"], "prompt_tps": t["prompt_per_second"], "gen_tps": t["predicted_per_second"], "wall_s": round(time.time() - t0, 2)})
    return {"gen_tps_median": round(statistics.median(r["gen_tps"] for r in rows), 1), "prompt_tps_median": round(statistics.median(r["prompt_tps"] for r in rows), 1), "runs": rows}


def asks(tag: str) -> dict[str, object]:
    b5.run_suites(tag, OUT, {}, serve=SERVE, port=8010)
    return b5.summarise(OUT, tag)


def audit_calls(path: Path, purpose: str) -> dict[str, object]:
    import duckdb

    if not path.exists():  # eval_extraction.py keeps its audit log in memory: only the totals it prints exist
        return {}
    con = duckdb.connect(str(path), read_only=True)
    rows = con.execute("select body from audit_events where kind = 'llm_call'").fetchall()
    con.close()
    ps = [json.loads(b)["payload"] for (b,) in rows]
    ps = [p for p in ps if p.get("purpose") == purpose and not p.get("cached")]
    lat = [p["latency_ms"] / 1000 for p in ps if p.get("latency_ms")]
    tok = sum(p.get("completion_tokens") or 0 for p in ps)
    return {"calls": len(ps), "median_s": round(statistics.median(lat), 2) if lat else None, "p95_s": p95(lat),
            "completion_tokens_per_call": round(tok / max(len(ps), 1)), "prompt_tokens_per_call": round(sum(p.get("prompt_tokens") or 0 for p in ps) / max(len(ps), 1)),
            "malformed_calls": sum(p.get("error") == "ValueError" for p in ps), "failed_calls": sum(bool(p.get("error")) for p in ps)}


def extract(tag: str) -> dict[str, object]:
    res: dict[str, object] = {}
    for source in ("notes", "transcripts"):
        audit = OUT / f"{tag}_extract_{source}_audit.duckdb"
        audit.unlink(missing_ok=True)
        env = {**os.environ, "KEPT_AUDIT_LOG_PATH": str(audit), "CUDA_VISIBLE_DEVICES": "", "HF_HUB_OFFLINE": "1", "PYTHONPATH": str(REPO / "src"), "KEPT_TEXT_LLM_MODEL": "llamacpp/qwen3.8-27b"}
        cmd = f"{SCOPE.format(cap='7G')} {sys.executable} {REPO}/scripts/eval_extraction.py --source {source} --split holdout --workers 2"
        p = subprocess.run(shlex.split(cmd), env=env, cwd=REPO, capture_output=True, text=True)
        (OUT / f"{tag}_extract_{source}.txt").write_text(p.stdout + p.stderr)
        m = re.search(r"(\d+) ok, (\d+) errors, (\d+)s", p.stdout)
        fields = {g[0]: {"f1": float(g[1]), "precision": float(g[2]), "recall": float(g[3]), "pass": g[4] == "PASS"}
                  for g in re.findall(r"^\s+(\w+)\s+f1 ([\d.]+)\s+p ([\d.]+)\s+r ([\d.]+)\s+(PASS|FAIL)", p.stdout, re.M)}
        res[source] = {"ok": int(m[1]) if m else 0, "errors": int(m[2]) if m else None, "seconds": int(m[3]) if m else None, "fields": fields,
                       **audit_calls(audit, "text.extract")} | ({} if m else {"crashed": p.stderr[-400:]})
    return res


def brief_sources() -> list[dict[str, object]]:
    """50 cases and their numbered sources, from `kept serve` (the sources don't depend on the model)."""
    path = OUT / "brief_sources.json"
    if path.exists():
        return json.loads(path.read_text())  # type: ignore[no-any-return]
    audit = OUT / "brief_sources_audit.duckdb"
    audit.unlink(missing_ok=True)
    env = {**os.environ, "CUDA_VISIBLE_DEVICES": "", "HF_HUB_OFFLINE": "1", "PYTHONPATH": str(REPO / "src"), "KEPT_AUDIT_LOG_PATH": str(audit)}
    server = subprocess.Popen(shlex.split(SERVE_AT.format(port=8011)), env=env, stdout=(OUT / "brief_sources_serve.log").open("w"), stderr=subprocess.STDOUT, start_new_session=True)
    api = "http://127.0.0.1:8011"
    try:
        t0 = time.time()
        while not b5._get(f"{api}/health"):
            if server.poll() is not None or time.time() - t0 > 900:
                raise RuntimeError("kept serve didn't start")
            time.sleep(3)
        get = lambda u: json.load(urllib.request.urlopen(f"{api}{u}", timeout=300))  # noqa: E731
        queue = get("/queue?user_id=b1&role=team_lead")
        cases = [q["case_id"] for q in queue][:500][:: 500 // N_BRIEFS][:N_BRIEFS]
        out = [{"case_id": c, "sources": get(f"/cases/{c}/brief?user_id=b1&role=team_lead")["sources"]} for c in cases]
    finally:
        os.killpg(server.pid, signal.SIGTERM)
        try:
            server.wait(60)
        except subprocess.TimeoutExpired:
            os.killpg(server.pid, signal.SIGKILL)
    path.write_text(json.dumps(out))
    return out


def briefs(tag: str) -> dict[str, object]:
    from concurrent.futures import ThreadPoolExecutor

    from kept.app.briefs import _CITE, _SCHEMA, CASE_SYSTEM, Source
    from kept.ask.grounding import ungrounded_numbers
    from kept.common.audit import DuckDBAuditLog
    from kept.common.llm import LiteLLMGateway, Purpose
    from kept.text.redact import fixed_text

    cases = brief_sources()
    audit = OUT / f"{tag}_briefs_audit.duckdb"
    audit.unlink(missing_ok=True)
    llm = LiteLLMGateway(model="llamacpp/qwen3.8-27b", audit_log=DuckDBAuditLog(audit), timeout_s=180)

    def one(c: dict[str, object]) -> dict[str, object]:
        srcs = [Source(**s) for s in c["sources"]]  # type: ignore[attr-defined]
        by_id = {s.id: s for s in srcs}
        doc = "\n".join(f"[{s.id}] {s.label}: {s.text}" for s in srcs)
        t0 = time.time()
        try:
            reply = llm.complete(system=CASE_SYSTEM, user=fixed_text(doc), purpose=Purpose.CASE_BRIEF, actor_id="b1", json_schema=_SCHEMA, temperature=0.0)
        except Exception as e:
            return {"case_id": c["case_id"], "failed": type(e).__name__, "s": round(time.time() - t0, 2)}
        bullets = (reply.parsed or {}).get("bullets", [])
        row = {"case_id": c["case_id"], "bullets": len(bullets), "no_cite": 0, "dropped_for_numbers": 0, "numbers_removed": 0, "kept": 0, "s": round(time.time() - t0, 2)}
        for b in bullets:
            cites = [x for x in dict.fromkeys(str(x).strip("[] ") for x in b.get("cites") or []) if x in by_id]
            text = _CITE.sub("", str(b.get("text", ""))).strip()
            if not text or not cites:
                row["no_cite"] += 1  # type: ignore[operator]
                continue
            bad = ungrounded_numbers(text, [[by_id[x].text] for x in cites])
            if bad:
                row["dropped_for_numbers"] += 1  # type: ignore[operator]
                row["numbers_removed"] += len(bad)  # type: ignore[operator]
            else:
                row["kept"] += 1  # type: ignore[operator]
        return row

    with ThreadPoolExecutor(2) as pool:
        rows = list(pool.map(one, cases))
    ok = [r for r in rows if "failed" not in r]
    secs = [float(r["s"]) for r in ok]
    return {"cases": len(rows), "failed": len(rows) - len(ok), "bullets": sum(r["bullets"] for r in ok),  # type: ignore[misc]
            "kept": sum(r["kept"] for r in ok), "no_cite": sum(r["no_cite"] for r in ok), "bullets_dropped_for_numbers": sum(r["dropped_for_numbers"] for r in ok),
            "numbers_removed": sum(r["numbers_removed"] for r in ok), "briefs_with_a_removal": sum(bool(r["dropped_for_numbers"] or r["no_cite"]) for r in ok),
            "briefs_with_no_bullet_left": sum(r["kept"] == 0 for r in ok), "median_s": round(statistics.median(secs), 2) if secs else None, "p95_s": p95(secs),
            **{k: v for k, v in audit_calls(audit, Purpose.CASE_BRIEF).items() if k in ("malformed_calls", "failed_calls", "completion_tokens_per_call", "prompt_tokens_per_call")}, "rows": rows}


# ---------------------------------------------------------------- run and report
def run(model: str, steps: list[str]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    name, gguf, _ = MODELS[model]
    path = OUT / f"{model}.json"
    res = json.loads(path.read_text()) if path.exists() else {}
    res |= {"name": name, "gguf": gguf.name, "gguf_gb": round(gguf.stat().st_size / 1e9, 2), "flags": "scripts/llm_server.sh: -np 2 -c 32768 -ctk q8_0 -ctv q8_0 -fa on, thinking off"}
    try:
        with LlamaServer(gguf) as srv:
            res["load_s"] = srv.load_s
            for step in steps:
                print(f"== {model} {step}", flush=True)
                if step == "briefs":
                    brief_sources()  # once, with whichever model is up: the sources don't depend on it
                res[step] = {"speed": speed, "asks": asks, "extract": extract, "briefs": briefs}[step](model)
                res["vram"] = srv.vram()
                path.write_text(json.dumps(res, indent=1))
            res["vram"] = srv.vram()
    except RuntimeError as e:  # the model does not load: that is a result
        res["load_error"] = str(e)
    path.write_text(json.dumps(res, indent=1))


def gate_doc() -> dict[str, object]:
    """The live model's holdout F1 and recall, read from docs/reports/extraction_gate.md (first table)."""
    rows = {}
    for line in (REPO / "docs/reports/extraction_gate.md").read_text().split("## Holdout")[1].split("\n\n")[1].splitlines()[2:]:
        c = [x.strip(" *") for x in line.strip("|").split("|")]
        rows[c[0]] = {"notes_f1": float(c[1]), "notes_recall": float(c[3]), "calls_f1": float(c[4]), "calls_recall": float(c[6])}
    return rows


def report() -> None:
    res: dict[str, object] = {}
    for m in MODELS:
        f = OUT / f"{m}.json"
        res[m] = json.loads(f.read_text()) if f.exists() else {}
    live = res["live"]
    live["asks"] = b5.summarise(b5.REPORTS / "decision_B5", "live")  # type: ignore[index]
    live["extract_from_doc"] = gate_doc()  # type: ignore[index]
    (REPORTS / "decision_B1.json").write_text(json.dumps(res, indent=1))
    print(figure(res))
    for m, r in res.items():
        a = r.get("asks", {}).get("all", {})
        print(m, r.get("vram"), a.get("right"), a.get("graded"), r.get("asks", {}).get("drill", {}).get("right"), a.get("median_s"), a.get("p95_s"), a.get("refusal_recall"), a.get("wrong_but_confident"), r.get("speed", {}).get("gen_tps_median"))


def figure(res: dict[str, dict]) -> str:  # type: ignore[type-arg]
    from reportlib import BLUE, INK, KEPT, MUTED, ORANGE, plt, save, style, tidy

    style()
    fig, (a, b) = plt.subplots(1, 2, figsize=(10, 4.2))
    colors = {"live": KEPT, "qwen3-14b": BLUE, "qwen3-8b": ORANGE, "gemma3-12b": INK}
    for m, r in res.items():
        s = r.get("asks", {}).get("all")
        if not s or not r.get("vram"):
            continue
        acc = 100 * s["accuracy"]
        for ax, x in ((a, r["vram"]["peak_mib"] / 1024), (b, s["median_s"])):
            ax.scatter([x], [acc], s=70, color=colors[m], zorder=3)
            ax.annotate(f"{r['name']}\ndrill {r['asks']['drill']['right']}/{r['asks']['drill']['graded']}", (x, acc), textcoords="offset points", xytext=(7, -4), fontsize=8, color=MUTED)
    a.set_xlabel("peak GPU memory (GiB)")
    b.set_xlabel("median seconds per Ask question")
    for ax in (a, b):
        ax.set_ylabel("Ask questions right (%), 3 suites")
        tidy(ax, "y")
    a.set_title("Accuracy against memory", loc="left")
    b.set_title("Accuracy against latency", loc="left")
    fig.tight_layout()
    return save(fig, "dec_B1")


def serve_at(port: int) -> None:
    """`kept serve` with its clock set to FEATURES_AS_OF, so the cards aren't stale (only for the brief sources)."""
    import dataclasses
    from datetime import datetime

    import uvicorn
    from dotenv import load_dotenv

    from kept.app.api import create_app
    from kept.app.real import real_services

    load_dotenv()
    at = datetime.fromisoformat(FEATURES_AS_OF)
    uvicorn.run(create_app(dataclasses.replace(real_services(), clock=lambda: at)), host="127.0.0.1", port=port)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["run", "report", "serve-at"])
    ap.add_argument("--port", type=int, default=8011)
    ap.add_argument("model", nargs="?", choices=list(MODELS))
    ap.add_argument("--steps", default="speed,asks,extract,briefs")
    a = ap.parse_args()
    if a.mode == "serve-at":
        serve_at(a.port)
    elif a.mode == "run":
        run(a.model, a.steps.split(","))
    else:
        report()


if __name__ == "__main__":
    main()
