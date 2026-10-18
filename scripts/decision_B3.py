# ruff: noqa: E501
"""Decision B3: the serving runtime. The same file, Qwen3-14B-Q4_K_M.gguf, on llama.cpp (scripts/llm_server.sh flags) and on
Ollama 0.20.3 (a private `ollama serve` on :11435 with its own model directory; the model is imported with a Modelfile
`FROM <path>` whose TEMPLATE is Qwen3's chat format with the empty think block already filled, which is what
enable_thinking=false does in llama.cpp). Three configurations, one at a time on the GPU:

    llamacpp        -np 2 -c 32768 (two 16k slots), q8 KV, flash attention
    ollama_default  no environment settings: Ollama's own defaults
    ollama_matched  OLLAMA_CONTEXT_LENGTH=16384 OLLAMA_NUM_PARALLEL=2 OLLAMA_FLASH_ATTENTION=1 OLLAMA_KV_CACHE_TYPE=q8_0

    uv run python scripts/decision_B3.py run [--only llamacpp,ollama_default,ollama_matched]
    uv run python scripts/decision_B3.py cleanup     # ollama rm and delete the private model directory
    uv run python scripts/decision_B3.py report      # -> data/exports/reports/decision_B3.json

Per configuration:
  context     a prompt of about 9,000 tokens (a fact planted at the start, a question at the end) sent through the
              OpenAI-style /v1 endpoint, and for Ollama also through /api/chat with num_ctx set explicitly; the prompt_tokens each
              server reports and whether the planted fact is answered.
  throughput  256-token generations, one request and two at once: total generated tokens per second.
  extraction  200 notes through scripts/eval_extraction.py with the JSON schema: replies that failed the schema.
  drill       the 30-question drill through `kept serve` (the live pipeline): right, p95 latency.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import statistics
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import decision_B1 as b1  # noqa: E402
import decision_B5 as b5  # noqa: E402

OUT = b5.REPORTS / "decision_B3"
GGUF = Path.home() / "models/b1/Qwen3-14B-Q4_K_M.gguf"
OLLAMA_DIR = Path.home() / "models/b3_ollama"
OLLAMA_PORT = 11435
TAG = "qwen3-14b-b3"
CONFIGS = {
    "llamacpp": {},
    "ollama_default": {},
    "ollama_matched": {"OLLAMA_CONTEXT_LENGTH": "16384", "OLLAMA_NUM_PARALLEL": "2", "OLLAMA_FLASH_ATTENTION": "1", "OLLAMA_KV_CACHE_TYPE": "q8_0"},
}
MODELFILE = f"""FROM {GGUF}
TEMPLATE \"\"\"{{{{- if .System }}}}<|im_start|>system
{{{{ .System }}}}<|im_end|>
{{{{ end }}}}{{{{- range .Messages }}}}<|im_start|>{{{{ .Role }}}}
{{{{ .Content }}}}<|im_end|>
{{{{ end }}}}<|im_start|>assistant
<think>

</think>

\"\"\"
PARAMETER stop <|im_end|>
PARAMETER temperature 0
"""
NEEDLE = "The access code for this session is 7391."
QUESTION = "\n\nQuestion: what is the access code for this session? Reply with the number only."
GEN_PROMPTS = [
    "Write a detailed, numbered guide of twelve practical steps for a collections agent preparing to call a customer who has missed two payments. Explain each step in three sentences.",
    "Describe, in twelve numbered paragraphs, how a bank should review a customer's hardship request fairly. Give each paragraph three sentences.",
]


def post(url: str, body: dict[str, object], timeout: int = 900) -> dict[str, object]:
    req = urllib.request.Request(url, json.dumps(body).encode(), {"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)  # type: ignore[no-any-return]


def nine_k_prompt(llama: str | None) -> tuple[str, int]:
    """About 9,000 tokens: the planted fact, then dated case lines. Built once against llama-server's tokenizer."""
    f = OUT / "prompt9k.json"
    if f.exists():
        d = json.loads(f.read_text())
        return d["text"], d["tokens"]
    assert llama, "build the prompt while llama-server is up"
    lines, text = [], ""
    for i in range(1, 2000):
        lines.append(f"Case CS-2026-{i:06d}: balance {1000 + (i * 37) % 9000}.{i % 100:02d} CAD, {i % 90} days past due, queue Q{i % 7}, last contact {1 + i % 28} Sep 2026.")
        text = NEEDLE + "\n\nHere are the case lines of the portfolio:\n" + "\n".join(lines) + QUESTION
        if i % 40 == 0 and len(post(f"{llama}/tokenize", {"content": text})["tokens"]) >= 9000:  # type: ignore[arg-type]
            break
    n = len(post(f"{llama}/tokenize", {"content": text})["tokens"])  # type: ignore[arg-type]
    f.write_text(json.dumps({"text": text, "tokens": n}))
    return text, n


def context_test(cfg: str, base: str) -> dict[str, object]:
    text, n = nine_k_prompt(base if cfg == "llamacpp" else None)
    res: dict[str, object] = {"prompt_tokens_sent": n}
    body = {"model": TAG, "messages": [{"role": "user", "content": text}], "max_tokens": 16, "temperature": 0}
    r = post(f"{base}/v1/chat/completions", body)
    res["openai_endpoint"] = {"prompt_tokens_reported": r["usage"]["prompt_tokens"], "reply": r["choices"][0]["message"]["content"].strip()[:60], "finds_planted_fact": "7391" in r["choices"][0]["message"]["content"]}  # type: ignore[index]
    if cfg != "llamacpp":
        r = post(f"{base}/api/chat", {"model": TAG, "messages": body["messages"], "stream": False, "options": {"num_ctx": 16384, "num_predict": 16, "temperature": 0}})
        res["native_num_ctx_16384"] = {"prompt_tokens_reported": r["prompt_eval_count"], "reply": r["message"]["content"].strip()[:60], "finds_planted_fact": "7391" in r["message"]["content"]}  # type: ignore[index]
    return res


def throughput(base: str) -> dict[str, object]:
    def gen(prompt: str) -> int:
        r = post(f"{base}/v1/chat/completions", {"model": TAG, "messages": [{"role": "user", "content": prompt}], "max_tokens": 256, "temperature": 0})
        return int(r["usage"]["completion_tokens"])  # type: ignore[index]

    gen("hi")  # warm up (loads the model on Ollama)
    res: dict[str, object] = {}
    for par in (1, 2):
        runs = []
        for rep in range(3):
            toks: list[int] = []
            ts = [threading.Thread(target=lambda p=p: toks.append(gen(p + f" (variant {rep})"))) for p in GEN_PROMPTS[:par]]
            t0 = time.time()
            for t in ts:
                t.start()
            for t in ts:
                t.join()
            wall = time.time() - t0
            runs.append({"wall_s": round(wall, 2), "tokens": sum(toks), "tps": round(sum(toks) / wall, 1)})
        res[f"parallel_{par}"] = {"tps_median": round(statistics.median(r["tps"] for r in runs), 1), "runs": runs}
    return res


def extraction(cfg: str, api: str) -> dict[str, object]:
    audit = OUT / f"{cfg}_extract_audit.duckdb"
    audit.unlink(missing_ok=True)
    env = {**os.environ, "KEPT_AUDIT_LOG_PATH": str(audit), "CUDA_VISIBLE_DEVICES": "", "HF_HUB_OFFLINE": "1", "PYTHONPATH": str(REPO / "src"), **model_env(cfg)}
    cmd = f"{b1.SCOPE.format(cap='7G')} {sys.executable} {REPO}/scripts/eval_extraction.py --source notes --split tune --limit 200 --workers 2"
    t0 = time.time()
    p = subprocess.run(shlex.split(cmd), env=env, cwd=REPO, capture_output=True, text=True)
    (OUT / f"{cfg}_extract.txt").write_text(p.stdout + p.stderr)
    import re

    m = re.search(r"(\d+) ok, (\d+) errors, (\d+)s", p.stdout)
    return {"calls_requested": 200, "texts_ok": int(m[1]) if m else 0, "texts_failed": int(m[2]) if m else None, "seconds": round(time.time() - t0), **b1.audit_calls(audit, "text.extract")}


def model_env(cfg: str) -> dict[str, str]:
    if cfg == "llamacpp":
        return {"KEPT_TEXT_LLM_MODEL": "llamacpp/qwen3.8-27b", "KEPT_ASK_LLM_MODEL": "llamacpp/qwen3.8-27b"}  # the alias llm_server.sh serves
    return {"KEPT_TEXT_LLM_MODEL": f"ollama/{TAG}", "KEPT_ASK_LLM_MODEL": f"ollama/{TAG}", "OLLAMA_API_BASE": f"http://127.0.0.1:{OLLAMA_PORT}"}


def drill(cfg: str) -> dict[str, object]:
    b5.SUITES = {"drill": b5.SUITES["drill"]}
    b5.run_suites(f"{cfg}_drill", OUT, {**model_env(cfg), "PYTHONPATH": str(REPO / "src")}, serve=b1.SERVE, port=8010)
    return b5.summarise(OUT, f"{cfg}_drill")["drill"]  # type: ignore[no-any-return]


class Ollama:
    def __init__(self, extra_env: dict[str, str]) -> None:
        self.env = {**os.environ, "OLLAMA_HOST": f"127.0.0.1:{OLLAMA_PORT}", "OLLAMA_MODELS": str(OLLAMA_DIR), "CUDA_VISIBLE_DEVICES": "0", **extra_env}

    def __enter__(self) -> Ollama:
        OLLAMA_DIR.mkdir(parents=True, exist_ok=True)
        self.log = (OUT / "ollama_serve.log").open("a")
        self.proc = subprocess.Popen(shlex.split(f"{b1.SCOPE.format(cap='12G')} ollama serve"), env=self.env, stdout=self.log, stderr=subprocess.STDOUT, start_new_session=True)
        t0 = time.time()
        while not b5._get(f"http://127.0.0.1:{OLLAMA_PORT}/api/version"):
            if time.time() - t0 > 120:
                raise RuntimeError("ollama didn't start")
            time.sleep(1)
        self.sampler = b1.Sampler()
        self.sampler.start()
        return self

    def __exit__(self, *exc: object) -> None:
        import signal

        self.sampler.stop_.set()
        os.killpg(self.proc.pid, signal.SIGTERM)
        try:
            self.proc.wait(60)
        except subprocess.TimeoutExpired:
            os.killpg(self.proc.pid, signal.SIGKILL)

    def cli(self, *args: str) -> str:
        p = subprocess.run(["ollama", *args], env=self.env, capture_output=True, text=True)
        return p.stdout + p.stderr


def ensure_model(o: Ollama) -> None:
    if TAG not in o.cli("list"):
        mf = OUT / "Modelfile"
        mf.write_text(MODELFILE)
        print(o.cli("create", TAG, "-f", str(mf)))


def run_config(cfg: str) -> dict[str, object]:
    res: dict[str, object] = {"env": CONFIGS[cfg]}
    if cfg == "llamacpp":
        with b1.LlamaServer(GGUF) as srv:
            base = "http://127.0.0.1:8081"
            res["context"] = context_test(cfg, base)
            res["throughput"] = throughput(base)
            res["extraction"] = extraction(cfg, base)
            res["drill"] = drill(cfg)
            res["vram"] = srv.vram()
        return res
    with Ollama(CONFIGS[cfg]) as o:
        ensure_model(o)
        base = f"http://127.0.0.1:{OLLAMA_PORT}"
        res["context"] = context_test(cfg, base)
        res["ollama_ps"] = o.cli("ps")
        res["throughput"] = throughput(base)
        res["extraction"] = extraction(cfg, base)
        res["drill"] = drill(cfg)
        res["vram_peak_mib"] = o.sampler.peak
        res["ollama_log_truncations"] = sum("truncating input prompt" in ln for ln in (OUT / "ollama_serve.log").read_text().splitlines())
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["run", "cleanup", "report"])
    ap.add_argument("--only", default=",".join(CONFIGS))
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    f = b5.REPORTS / "decision_B3.json"
    res = json.loads(f.read_text()) if f.exists() else {}
    if a.mode == "run":
        for cfg in a.only.split(","):
            print(f"== {cfg}", flush=True)
            res[cfg] = run_config(cfg)
            f.write_text(json.dumps(res, indent=1))
    elif a.mode == "cleanup":
        with Ollama({}) as o:
            print(o.cli("rm", TAG))
        import shutil

        shutil.rmtree(OLLAMA_DIR, ignore_errors=True)
    else:
        print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
