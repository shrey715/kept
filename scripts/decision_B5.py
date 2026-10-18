# ruff: noqa: E501
"""Decision B5: what each step of the Ask adds. The same model (Qwen3.8-27B, `make llm`) answers the three question sets
with the pipeline built up one step at a time (KEPT_ASK_ABLATION, evaluation only; kept.ask.service.ABLATIONS):

    plain      one SQL prompt with the schema, the guard, run, narrate (the safety rules and the guard always stay on)
    route      + the scope classifier, the router, certified metrics, policy search, call summaries
    templates  + the reviewed SQL templates, date hints, worked examples and the intent checks
    drafts     + three SQL drafts and a majority vote
    lint       + the convention linter and one repair round
    live       + escalation to five drafts and the judge (the product)

    uv run python scripts/decision_B5.py run [--only plain,route]   # `make llm` first; starts `kept serve` per setting
    uv run python scripts/decision_B5.py report                    # -> data/exports/reports/decision_B5.json, dec_B5.png

Each setting gets a fresh server (so no reply cache carries over) with its own audit log, from which the LLM calls and
tokens per question are counted. Questions are asked through scripts/bench_run.py, graded as in docs/reports/ask_accuracy.md.
Wrong but confident: an answer (not a refusal) that the grader marks wrong.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import signal
import socket
import statistics
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("KEPT_DATA_DIR", REPO / "data"))  # data/ is not in a git worktree: point at the checkout's
REPORTS = DATA / "exports" / "reports"
SUITES = {
    "released": (DATA / "benchmark" / "benchmark_questions.csv", DATA / "benchmark" / "benchmark_dev_answers.csv"),
    "stress": (REPO / "benchmarks" / "stress_questions.csv", REPO / "benchmarks" / "stress_gold.csv"),
    "drill": (REPO / "benchmarks" / "drill_questions.csv", REPO / "benchmarks" / "drill_gold.csv"),
}
SETTINGS = ("plain", "route", "templates", "drafts", "lint", "live")
LABELS = {
    "plain": "One SQL prompt",
    "route": "+ router, scope, certified metrics",
    "templates": "+ templates and intent checks",
    "drafts": "+ three drafts, vote",
    "lint": "+ linter and repair",
    "live": "+ escalation and judge (live)",
}
SERVE = "uv run kept serve --port {port}"


def _port_open(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def _get(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def run_suites(tag: str, out: Path, env: dict[str, str], *, serve: str = SERVE, port: int = 8010) -> None:
    """Start `kept serve` with `env` (plus its own audit log), ask the three suites, stop it. Writes
    <out>/<tag>_<suite>.csv/.json, <tag>_audit.duckdb and <tag>_windows.json (each suite's start and end)."""
    out.mkdir(parents=True, exist_ok=True)
    audit = out / f"{tag}_audit.duckdb"
    audit.unlink(missing_ok=True)
    env = {**os.environ, "CUDA_VISIBLE_DEVICES": "", "HF_HUB_OFFLINE": "1", "KEPT_AUDIT_LOG_PATH": str(audit), **env}
    log = (out / f"{tag}_serve.log").open("w")
    while _port_open(port):  # the previous setting's server may still be shutting down
        time.sleep(2)
    server = subprocess.Popen(shlex.split(serve.format(port=port)), env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    api = f"http://127.0.0.1:{port}"
    try:
        t0 = time.time()
        while not _get(f"{api}/health"):
            if server.poll() is not None or time.time() - t0 > 900:
                raise RuntimeError(f"kept serve didn't start: see {log.name}")
            time.sleep(3)
        windows = {"startup_s": round(time.time() - t0, 1)}
        for suite, (questions, gold) in SUITES.items():
            start = time.time()
            subprocess.run(
                [sys.executable, str(REPO / "scripts" / "bench_run.py"), str(questions), "--gold", str(gold),
                 "--api", api, "--out", str(out / f"{tag}_{suite}.csv")],
                check=True,
            )
            windows[suite] = [start, time.time()]
            (out / f"{tag}_windows.json").write_text(json.dumps(windows))
    finally:
        os.killpg(server.pid, signal.SIGTERM)  # the whole group: systemd-run's scope and the server under it
        try:
            server.wait(60)
        except subprocess.TimeoutExpired:
            os.killpg(server.pid, signal.SIGKILL)


def _p95(xs: list[float]) -> float:
    return round(statistics.quantiles(xs, n=20)[-1], 1) if len(xs) >= 2 else (xs[0] if xs else 0.0)


def llm_per_question(audit: Path, start: float, end: float) -> list[dict[str, float]]:
    """One entry per Ask question in [start, end]: the LLM calls made for it (cached replies apart) and their tokens.
    The Ask logs its question after answering, so every LLM call before it, since the one before, is its own."""
    con = duckdb.connect(str(audit), read_only=True)
    rows = con.execute(
        "select kind, body from audit_events where at_us between ? and ? order by seq",
        [int(start * 1e6), int(end * 1e6)],
    ).fetchall()
    con.close()
    out, cur = [], {"calls": 0, "cached": 0, "prompt_tokens": 0, "completion_tokens": 0, "llm_ms": 0, "malformed": 0}
    for kind, body in rows:
        if kind == "llm_call":
            p = json.loads(body)["payload"]
            if p.get("cached"):
                cur["cached"] += 1
                continue
            cur["calls"] += 1
            cur["prompt_tokens"] += p.get("prompt_tokens") or 0
            cur["completion_tokens"] += p.get("completion_tokens") or 0
            cur["llm_ms"] += p.get("latency_ms") or 0
            cur["malformed"] += p.get("error") == "ValueError"  # a reply that failed its JSON schema
        elif kind == "ask_query":
            out.append(cur)
            cur = dict.fromkeys(cur, 0)
    return out


def summarise(out: Path, tag: str) -> dict[str, object]:
    """Accuracy, refusal recall, wrong-but-confident answers, LLM calls and latency for one run, per suite and in total."""
    windows = json.loads((out / f"{tag}_windows.json").read_text())
    res: dict[str, object] = {"startup_s": windows.get("startup_s")}
    every: list[dict[str, object]] = []
    calls: list[dict[str, float]] = []
    for suite in SUITES:
        rows = json.loads((out / f"{tag}_{suite}.json").read_text())
        per_q = llm_per_question(out / f"{tag}_audit.duckdb", *windows[suite])
        res[suite] = _score(rows, per_q)
        every += rows
        calls += per_q
    res["all"] = _score(every, calls)
    return res


def _score(rows: list[dict[str, object]], per_q: list[dict[str, float]]) -> dict[str, object]:
    graded = [r for r in rows if r["correct"] is not None]
    refuse = [r for r in graded if r["should_refuse"]]
    answerable = [r for r in graded if not r["should_refuse"]]
    answered = [r for r in answerable if r["rung"] not in ("refused", "clarify")]
    ms = [float(r["ms"]) / 1000 for r in rows]  # type: ignore[arg-type]
    n_calls = [q["calls"] for q in per_q]
    return {
        "questions": len(rows),
        "graded": len(graded),
        "right": sum(r["correct"] is True for r in graded),
        "accuracy": round(sum(r["correct"] is True for r in graded) / len(graded), 4),
        "in_scope": len(answerable),
        "in_scope_right": sum(r["correct"] is True for r in answerable),
        "should_refuse": len(refuse),
        "refused_right": sum(r["correct"] is True for r in refuse),
        "refusal_recall": round(sum(r["correct"] is True for r in refuse) / len(refuse), 4) if refuse else None,
        "wrong_but_confident": sum(r["correct"] is False for r in answered),
        "wrongly_refused": len(answerable) - len(answered),
        "rungs": {k: sum(r["rung"] == k for r in rows) for k in sorted({str(r["rung"]) for r in rows})},
        "median_s": round(statistics.median(ms), 1),
        "p95_s": _p95(ms),
        "asks_logged": len(per_q),
        "llm_calls_per_question": round(sum(n_calls) / len(rows), 2),
        "llm_calls_median": statistics.median(n_calls) if n_calls else None,
        "llm_calls_max": max(n_calls) if n_calls else None,
        "cached_replies": sum(q["cached"] for q in per_q),
        "malformed_replies": sum(q["malformed"] for q in per_q),
        "prompt_tokens_per_question": round(sum(q["prompt_tokens"] for q in per_q) / len(rows)),
        "completion_tokens_per_question": round(sum(q["completion_tokens"] for q in per_q) / len(rows)),
        "tokens_per_s": round(sum(q["completion_tokens"] for q in per_q) / max(sum(q["llm_ms"] for q in per_q) / 1000, 1e-9), 1),
    }


def figure(results: dict[str, dict[str, object]]) -> str:
    sys.path.insert(0, str(REPO / "scripts"))
    from reportlib import BLUE, INK, KEPT, MUTED, ORANGE, plt, save, style, tidy

    style()
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(10, 4.2), gridspec_kw={"width_ratios": [3, 1.3]})
    names = [s for s in SETTINGS if s in results]
    y = list(range(len(names)))[::-1]
    for i, (suite, color) in enumerate(zip(SUITES, (BLUE, ORANGE, INK), strict=True)):
        vals = [100 * float(results[s][suite]["accuracy"]) for s in names]  # type: ignore[index]
        ax.barh([v + (1 - i) * 0.26 for v in y], vals, height=0.25, color=color, label=suite)
        for yi, v, s in zip(y, vals, names, strict=True):
            r = results[s][suite]  # type: ignore[index]
            ax.text(v + 1, yi + (1 - i) * 0.26, f"{r['right']}/{r['graded']}", va="center", fontsize=7, color=MUTED)
    ax.set_yticks(y, [LABELS[s] for s in names])
    ax.set_xlim(0, 112)
    ax.set_xlabel("questions right (%)", labelpad=2)
    ax.set_title("Accuracy as each step is added (same model)", loc="left")
    ax.legend(frameon=False, fontsize=8, loc="upper center", bbox_to_anchor=(0.45, -0.18), ncol=3)
    tidy(ax)
    wbc = [int(results[s]["all"]["wrong_but_confident"]) for s in names]  # type: ignore[index]
    bx.barh(y, wbc, height=0.55, color=KEPT)
    for yi, v, s in zip(y, wbc, names, strict=True):
        a = results[s]["all"]  # type: ignore[index]
        bx.text(v + 0.3, yi, f"{v}  ({a['llm_calls_per_question']} calls, {a['median_s']} s)", va="center", fontsize=7)
    bx.set_yticks(y, [""] * len(names))
    bx.set_xlim(0, max([*wbc, 1]) * 2.2)
    bx.set_xlabel("wrong but confident (all suites)")
    tidy(bx)
    return save(fig, "dec_B5")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["run", "report"])
    ap.add_argument("--only", default=",".join(SETTINGS))
    ap.add_argument("--serve", default=SERVE, help="command that starts the API; {port} is filled in")
    ap.add_argument("--port", type=int, default=8010)
    a = ap.parse_args()
    out = REPORTS / "decision_B5"
    if a.mode == "run":
        for s in a.only.split(","):
            print(f"== {s}", flush=True)
            run_suites(s, out, {"KEPT_ASK_ABLATION": s}, serve=a.serve, port=a.port)
        return
    results = {s: summarise(out, s) for s in SETTINGS if (out / f"{s}_windows.json").exists()}
    (REPORTS / "decision_B5.json").write_text(
        json.dumps({"model": "Qwen3.8-27B UD-Q3_K_XL, llama.cpp, -np 2 -c 32768", "settings": results}, indent=1)
    )
    print(figure(results))
    for s, r in results.items():
        line = "  ".join(f"{k} {r[k]['right']}/{r[k]['graded']}" for k in SUITES)  # type: ignore[index]
        a_ = r["all"]
        print(f"{s:10} {line}  wbc {a_['wrong_but_confident']}  refusal {a_['refusal_recall']}  calls {a_['llm_calls_per_question']}  median {a_['median_s']}s p95 {a_['p95_s']}s")  # type: ignore[index]


if __name__ == "__main__":
    main()
