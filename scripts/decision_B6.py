"""B6: policy search: BM25, dense, hybrid RRF (live), hybrid + cross-encoder rerank, four embedders.
Gold: benchmarks/retrieval_gold.csv (document + section per question). Everything runs on the CPU.
Usage (capped): CUDA_VISIBLE_DEVICES= HF_HUB_OFFLINE=1 uv run python scripts/decision_B6.py
Writes data/exports/reports/decision_B6.json and docs/reports/figures/dec_B6.png.
"""

from __future__ import annotations

import csv
import gc
import json
import re
import statistics
import tempfile
import time
from datetime import date
from pathlib import Path

from reportlib import AQUA, BLUE, INK, MUTED, ORANGE, plt, save, style, tidy

from kept.ask.policy import PolicyIndex, build_policy_index

REPO = Path(__file__).resolve().parents[1]
DATA = Path("/home/akshat/hackathons/kept/data")  # data/ is gitignored: the main checkout holds it
OUT = DATA / "exports" / "reports" / "decision_B6.json"
EMBEDDERS = {  # name -> (passage prefix, query prefix)
    "BAAI/bge-m3": ("", ""),
    "intfloat/multilingual-e5-base": ("passage: ", "query: "),
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2": ("", ""),
    "sentence-transformers/all-MiniLM-L6-v2": ("", ""),
}
RERANKER = "cross-encoder/ms-marco-MiniLM-L-6-v2"
POOL = 10  # hybrid candidates the cross-encoder reorders; recall@k beyond 10 is not measured
CONFIGS = ("bm25", "dense", "hybrid", "hybrid+rerank")


def read_csv(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def load_gold() -> list[dict[str, str]]:
    with open(REPO / "benchmarks" / "retrieval_gold.csv", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def gold_targets(gold: str) -> list[tuple[str, str | None]]:
    """'POL-COLL-001 §5.2; FAQ-COLL-001' -> [(doc, '§5.2'), (doc, None)]: any one is a hit."""
    out: list[tuple[str, str | None]] = []
    for part in gold.split(";"):
        doc, _, sec = part.strip().partition(" ")
        out.append((doc, sec or None))
    return out


def is_hit(doc: str, section: str, targets: list[tuple[str, str | None]]) -> bool:
    return any(doc == d and (s is None or re.search(re.escape(s) + r"(?!\d)", section)) for d, s in targets)


def first_hit(ranked: list[tuple[str, str]], targets: list[tuple[str, str | None]]) -> int | None:
    """1-based rank of the first hit, or None."""
    return next((i for i, (d, s) in enumerate(ranked, 1) if is_hit(d, s, targets)), None)


def metrics(ranks: list[int | None]) -> dict[str, float]:
    n = len(ranks)
    return {
        "n": n,
        "recall@1": sum(r is not None and r <= 1 for r in ranks) / n,
        "recall@3": sum(r is not None and r <= 3 for r in ranks) / n,
        "recall@5": sum(r is not None and r <= 5 for r in ranks) / n,
        "mrr": sum(1 / r for r in ranks if r) / n,
    }


def make_embedders(name: str):
    from sentence_transformers import SentenceTransformer

    passage, query = EMBEDDERS[name]
    st = SentenceTransformer(name, device="cpu", local_files_only=True)

    def enc(prefix: str):
        return lambda texts: st.encode(
            [prefix + t for t in texts], normalize_embeddings=True, batch_size=16
        ).tolist()

    return enc(passage), enc(query), st


def run_embedder(name: str, gold: list[dict[str, str]], reranker) -> dict:
    docs, events = (read_csv(DATA / "raw" / f"{n}.csv") for n in ("reference_documents", "ops_events"))
    embed_p, embed_q, st = make_embedders(name)
    with tempfile.TemporaryDirectory() as tmp:
        index = PolicyIndex(Path(tmp), embed_p)
        t0 = time.perf_counter()
        n_chunks = build_policy_index(index, docs, DATA / "policy", events)
        build_s = time.perf_counter() - t0
        index._embed = embed_q  # queries get the query prefix; the index was built with the passage one

        def rank(q: dict[str, str], config: str) -> list[tuple[str, str]]:
            as_of = date.fromisoformat(q["as_of"])
            if config == "hybrid+rerank":
                hits = index.search(q["question"], as_of=as_of, k=POOL)
                scores = reranker.predict([(q["question"], h.snippet) for h in hits], batch_size=POOL)
                hits = [h for _, h in sorted(zip(scores, hits, strict=True), key=lambda p: -p[0])]
            else:
                hits = index.search(q["question"], as_of=as_of, k=POOL, mode=config)
            return [(h.document_id, h.section) for h in hits]

        index.search("warm up", as_of=date(2026, 9, 28), k=POOL)
        reranker.predict([("warm", "up")])
        res: dict = {"chunks": n_chunks, "index_build_s": round(build_s, 2), "configs": {}}
        for config in CONFIGS:
            ranks: list[int | None] = []
            lat: list[float] = []
            for q in gold:
                t = time.perf_counter()
                ranked = rank(q, config)
                lat.append((time.perf_counter() - t) * 1000)
                ranks.append(first_hit(ranked, gold_targets(q["gold"])))
            fr = [r for r, q in zip(ranks, gold, strict=True) if q["lang"] == "fr"]
            en = [r for r, q in zip(ranks, gold, strict=True) if q["lang"] == "en"]
            lat.sort()
            res["configs"][config] = {
                "all": metrics(ranks),
                "fr": metrics(fr),
                "en": metrics(en),
                "benchmark_questions": metrics(
                    [r for r, q in zip(ranks, gold, strict=True) if q["origin"] != "paraphrase"]
                ),
                "paraphrased_questions": metrics(
                    [r for r, q in zip(ranks, gold, strict=True) if q["origin"] == "paraphrase"]
                ),
                "latency_ms_median": round(statistics.median(lat), 1),
                "latency_ms_p95": round(lat[int(0.95 * (len(lat) - 1))], 1),
                "missed": [q["question_id"] for r, q in zip(ranks, gold, strict=True) if r is None or r > 5],
            }
            print(
                name, config, res["configs"][config]["all"], res["configs"][config]["fr"]["mrr"], flush=True
            )
    del st, embed_p, embed_q
    gc.collect()
    return res


def draw(results: dict) -> None:
    style()
    names = list(results["embedders"])
    short = [n.split("/")[-1].replace("paraphrase-multilingual-", "para-multi-") for n in names]
    fig, axes = plt.subplots(1, 2, figsize=(9.5, 3.8), sharey=True)
    colours = {"bm25": MUTED, "dense": BLUE, "hybrid": AQUA, "hybrid+rerank": ORANGE}
    for ax, lang, title in zip(
        axes,
        ("all", "fr"),
        (f"All {results['gold_questions']} questions", f"French only ({results['french_questions']})"),
        strict=True,
    ):
        w = 0.2
        for j, c in enumerate(CONFIGS):
            vals = [results["embedders"][n]["configs"][c][lang]["mrr"] for n in names]
            bars = ax.bar([i + (j - 1.5) * w for i in range(len(names))], vals, w, color=colours[c], label=c)
            for b, v in zip(bars, vals, strict=True):
                ax.text(b.get_x() + w / 2, v + 0.01, f"{v:.2f}", ha="center", fontsize=6, color=INK)
        ax.set_xticks(range(len(names)), short, rotation=12, fontsize=7)
        ax.set_title(title)
        tidy(ax, "y")
    axes[0].set_ylabel("MRR (higher is better)")
    axes[0].legend(fontsize=7, frameon=False, loc="upper center", ncol=4, bbox_to_anchor=(1.05, 1.0))
    axes[0].set_ylim(0, 1.15)
    save(fig, "dec_B6")


def main() -> None:
    from sentence_transformers import CrossEncoder

    gold = load_gold()
    reranker = CrossEncoder(RERANKER, device="cpu", local_files_only=True)
    results: dict = {
        "gold_questions": len(gold),
        "french_questions": sum(q["lang"] == "fr" for q in gold),
        "pool": POOL,
        "reranker": RERANKER,
        "embedders": {},
    }
    for name in EMBEDDERS:
        results["embedders"][name] = run_embedder(name, gold, reranker)
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(results, indent=2))
    draw(results)


if __name__ == "__main__":
    main()
