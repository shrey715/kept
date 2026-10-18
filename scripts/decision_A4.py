# ruff: noqa: E501  (report labels)
"""Decision A4: identity from exact keys only, vs exact keys + Splink (live), vs a small embedding matcher.

    uv run python scripts/decision_A4.py [--warehouse data/warehouse/eval_copy.duckdb] [--data data] [--part split|recall|embed|assemble]

Read-only on the warehouse. Writes data/exports/reports/decision_A4.json and docs/reports/figures/dec_A4.png.
1. Links per exact rule, and the full matcher run again with its Splink stage off (identity_injection.no_splink):
   golden IDs and the people the exact keys alone would split, with the open balances on their cases.
2. Recall on the 200 planted duplicates (scripts/identity_injection.py) with and without Splink.
3. Optional: an embedding matcher (name, first name, DOB, postal code through BAAI/bge-small-en-v1.5 on the CPU,
   cosine threshold). The threshold is set on another 5% DOB-hash sample (hash % 20 = 1) to reach the design's 98%
   precision against the live crosswalk; then tested on the planted duplicates (sample 0) and the 300 reviewed pairs.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from identity_injection import KINDS, measure, no_splink
from reportlib import AQUA, BLUE, KEPT, plt, save, style, tidy

from kept.config import DATA_DIR, MATCH_PRECISION_TARGET
from kept.data.identity.exact import EXACT_RULES, exact_link_pairs
from kept.data.identity.pipeline import run_matching

KEY = ["source_system", "source_key"]


def identity_split(conn: duckdb.DuckDBPyConnection, data: Path) -> dict[str, Any]:
    """Exact keys only on every record vs the live crosswalk (exact + Splink, the full run)."""
    evidence = conn.sql("select * from silver.int_identity_evidence").df()
    per_rule = exact_link_pairs(evidence)["rule"].value_counts()
    del evidence
    summary_file = sorted((data / "exports" / "identity_crosswalk").glob("run_summary_*-full*.json"))[-1]
    summary = json.loads(summary_file.read_text())

    t0 = time.perf_counter()
    with no_splink():
        exact = run_matching(conn, verdicts=pd.DataFrame(), at=datetime(2026, 10, 16, tzinfo=UTC)).crosswalk
    exact_seconds = time.perf_counter() - t0
    live = conn.sql(
        "select golden_customer_id, source_system, source_key, match_rule from gold.identity_crosswalk where valid_to is null"
    ).df()
    both = live.merge(
        exact[[*KEY, "golden_customer_id"]], on=KEY, suffixes=("_live", "_exact"), validate="1:1"
    )
    assert len(both) == len(live) == len(exact), "the two runs must cover the same keys"
    parts = both.groupby("golden_customer_id_live")["golden_customer_id_exact"].nunique()
    split = parts[parts > 1]
    joined = both.groupby("golden_customer_id_exact")["golden_customer_id_live"].nunique()

    # open cases: is the case's person split, and which of their accounts leave the case's cluster
    cases = conn.sql(
        "select case_id, coll_customer_ref as source_key, total_overdue from silver.collections_cases where outcome_date is null"
    ).df()
    cases = cases.merge(both[both.source_system == "collections"], on="source_key", how="left")
    assert cases.golden_customer_id_live.notna().all()
    lost = both.merge(
        cases[["case_id", "golden_customer_id_live", "golden_customer_id_exact"]],
        on="golden_customer_id_live",
        suffixes=("", "_case"),
    )
    lost = lost[
        lost.golden_customer_id_exact != lost.golden_customer_id_exact_case
    ]  # in the person, not in the case's cluster
    lost_by = lost.groupby("source_system")["case_id"].nunique()
    is_split = cases.golden_customer_id_live.isin(split.index)
    return {
        "keys": len(live),
        "summary_file": summary_file.name,
        "exact_pairs_by_rule": {r: int(per_rule.get(r, 0)) for r in EXACT_RULES},
        "exact_pairs_total": int(per_rule.sum()),
        "exact_pairs_full_run": summary["exact_pairs"],
        "splink_pairs_auto_full_run": summary["splink_pairs_auto"],
        "splink_pairs_review_full_run": summary["splink_pairs_review"],
        "keys_by_strongest_link_live": {k: int(v) for k, v in live.match_rule.value_counts().items()},
        "golden_ids_live": int(live.golden_customer_id.nunique()),
        "golden_ids_exact_only": int(exact.golden_customer_id.nunique()),
        "multi_key_live": int((live.groupby("golden_customer_id").size() > 1).sum()),
        "multi_key_exact_only": int((exact.groupby("golden_customer_id").size() > 1).sum()),
        "people_split_exact_only": len(split),
        "records_in_split_people": int(both.golden_customer_id_live.isin(split.index).sum()),
        "exact_clusters_spanning_two_live_people": int((joined > 1).sum()),
        "open_cases": len(cases),
        "open_cases_person_split": int(is_split.sum()),
        "open_balance_total": float(cases.total_overdue.sum()),
        "open_balance_person_split": float(cases.total_overdue[is_split].sum()),
        "open_cases_losing_a_key_by_system": {k: int(v) for k, v in lost_by.items()},
        "open_cases_losing_any_key": int(lost.case_id.nunique()),
        "exact_only_run_seconds": round(exact_seconds, 1),
    }


def recall(warehouse: str, splink: bool) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    t0 = time.perf_counter()
    m = measure(warehouse, 20, 40, splink=splink)
    by_kind = m["found"].groupby("kind", sort=False)["merged"].agg(["sum", "size"])
    return {
        "merged": int(m["found"].merged.sum()),
        "planted": len(m["found"]),
        "by_kind": {k: int(r["sum"]) for k, r in by_kind.iterrows()},
        "wrong_merges": m["wrong"],
        "other_clusters_moved": m["moved"],
        "clusters_in_sample": m["clusters"],
        "seconds_two_runs": round(time.perf_counter() - t0, 1),
    }, m["planted"]


def _text(frame: pd.DataFrame, side: str = "") -> list[str]:
    cols = [f"{side}{c}" for c in ("name_key", "first_name_key", "dob", "postal_code")]
    return [
        " ".join(str(v) for v in row if isinstance(v, str) and v)
        for row in frame[cols].itertuples(index=False)
    ]


def _top1(emb: np.ndarray, chunk: int = 2048) -> tuple[np.ndarray, np.ndarray]:
    """Each row's nearest other row by cosine (embeddings are normalised): index and similarity."""
    idx, sim = np.empty(len(emb), dtype=np.int64), np.empty(len(emb), dtype=np.float32)
    for s in range(0, len(emb), chunk):
        block = emb[s : s + chunk] @ emb.T
        block[np.arange(len(block)), np.arange(s, s + len(block))] = -1  # not itself
        idx[s : s + chunk] = block.argmax(1)
        sim[s : s + chunk] = block.max(1)
    return idx, sim


def embedding_matcher(
    conn: duckdb.DuckDBPyConnection, data: Path, planted: list[dict[str, Any]]
) -> dict[str, Any]:
    os.environ["HF_HUB_OFFLINE"] = "1"  # the cached model only: never a download
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer("BAAI/bge-small-en-v1.5", device="cpu")
    live = conn.sql(
        "select source_system, source_key, golden_customer_id from gold.identity_crosswalk where valid_to is null"
    ).df()

    def sample(mod: int) -> pd.DataFrame:
        recs = conn.sql(
            f"select * from silver.int_identity_records where dob is not null and hash(dob) % 20 = {mod}"
        ).df()
        return recs.merge(live, on=KEY, how="left")

    def encode(texts: list[str]) -> np.ndarray:
        return model.encode(texts, batch_size=256, normalize_embeddings=True, convert_to_numpy=True).astype(
            np.float32
        )

    # threshold: the lowest cosine whose top-1 links reach the design's precision on validation sample 1
    val = sample(1)
    t0 = time.perf_counter()
    v_emb = encode(_text(val))
    embed_seconds_val = time.perf_counter() - t0
    v_idx, v_sim = _top1(v_emb)
    v_true = val.golden_customer_id.to_numpy() == val.golden_customer_id.to_numpy()[v_idx]
    order = np.argsort(-v_sim)
    precision_at = np.cumsum(v_true[order]) / np.arange(1, len(order) + 1)
    ok = np.flatnonzero(precision_at >= MATCH_PRECISION_TARGET)
    threshold = float(v_sim[order][ok.max()]) if len(ok) else 1.0

    # test: sample 0 plus the planted duplicates (the injection test's records), and the reviewed pairs
    test = sample(0)
    rows = pd.DataFrame([p["row"] for p in planted])
    t0 = time.perf_counter()
    t_emb = encode(_text(test))
    embed_seconds = time.perf_counter() - t0
    p_emb = encode(_text(rows))
    t0 = time.perf_counter()
    t_idx, t_sim = _top1(t_emb)
    knn_seconds = time.perf_counter() - t0
    linked = t_sim >= threshold
    agree = test.golden_customer_id.to_numpy()[linked] == test.golden_customer_id.to_numpy()[t_idx[linked]]

    pos = {k: i for i, k in enumerate(test.source_system + ":" + test.source_key)}
    sims = p_emb @ t_emb.T
    merged, wrong = [], 0
    for p, s in zip(planted, sims, strict=True):
        orig = pos["crm:" + p["original"]]
        hits = np.flatnonzero(s >= threshold)
        merged.append(orig in hits)
        others = test.golden_customer_id.to_numpy()[hits[hits != orig]]
        wrong += bool((others != test.golden_customer_id.iloc[orig]).any())
    found = pd.DataFrame({"kind": [p["kind"] for p in planted], "merged": merged})

    reviewed = pd.read_csv(data / "labels" / "match_pairs.csv", dtype=str)
    a, b = encode(_text(reviewed, "left_")), encode(_text(reviewed, "right_"))
    r_link = (a * b).sum(1) >= threshold
    r_true = reviewed.is_true_match.str.upper().eq("TRUE").to_numpy()
    return {
        "model": "BAAI/bge-small-en-v1.5 (cached), CPU",
        "fields": "name_key, first_name_key, dob, postal_code",
        "threshold_cosine": round(threshold, 4),
        "threshold_set_on": f"sample hash(dob) % 20 = 1: {len(val):,} records, top-1 neighbour precision >= {MATCH_PRECISION_TARGET} against the live crosswalk",
        "test_records": len(test),
        "test_top1_links": int(linked.sum()),
        "test_top1_agree_with_live": round(float(agree.mean()), 4) if len(agree) else None,
        "planted_merged": int(found.merged.sum()),
        "planted": len(found),
        "planted_by_kind": {k: int(g.merged.sum()) for k, g in found.groupby("kind", sort=False)},
        "planted_wrong_links": int(wrong),
        "reviewed_pairs": len(reviewed),
        "reviewed_true": int(r_true.sum()),
        "reviewed_linked": int(r_link.sum()),
        "reviewed_linked_true": int((r_link & r_true).sum()),
        "reviewed_precision": round(float(r_true[r_link].mean()), 4) if r_link.any() else None,
        "reviewed_recall_of_true": round(float(r_link[r_true].mean()), 4),
        "embed_seconds_per_1k_records": round(
            1000 * (embed_seconds + embed_seconds_val) / (len(test) + len(val)), 2
        ),
        "embed_seconds_test": round(embed_seconds, 1),
        "knn_seconds_test": round(knn_seconds, 1),
    }


def figure(out: dict[str, Any]) -> str:
    style()
    kinds = list(KINDS)
    series = [
        ("Exact keys only", out["recall_exact_only"]["by_kind"], AQUA),
        ("Exact + Splink (live)", out["recall_with_splink"]["by_kind"], KEPT),
    ]
    if out.get("embedding"):
        series.insert(1, ("Embedding matcher", out["embedding"]["planted_by_kind"], BLUE))
    fig, ax = plt.subplots(figsize=(7.2, 3.2))
    h = 0.8 / len(series)
    y = np.arange(len(kinds))[::-1]
    for i, (label, by_kind, colour) in enumerate(series):
        v = [by_kind.get(k, 0) for k in kinds]
        ax.barh(y + (len(series) / 2 - i - 0.5) * h, v, height=h, color=colour, label=label)
        for yi, vi in zip(y + (len(series) / 2 - i - 0.5) * h, v, strict=True):
            ax.text(vi + 0.4, yi, f"{vi}", va="center", fontsize=7)
    ax.set_yticks(y, kinds)
    ax.set_xlim(0, 46)
    ax.set_xlabel("Planted duplicates merged with their original (of 40 per kind)")
    ax.set_title("Recall on 200 planted duplicates, 5% sample", loc="left")
    ax.legend(frameon=False, fontsize=8, loc="lower right")
    tidy(ax)
    return save(fig, "dec_A4")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--warehouse", default=str(DATA_DIR / "warehouse" / "eval_copy.duckdb"))
    ap.add_argument("--data", type=Path, default=DATA_DIR)
    ap.add_argument("--part", choices=["split", "recall", "embed", "assemble"], default="assemble")
    a = ap.parse_args()
    conn = duckdb.connect(a.warehouse, read_only=True)
    conn.execute("SET memory_limit='3GB'; SET threads=4")
    conn.execute(f"SET temp_directory='{os.environ.get('KEPT_DUCK_TMP', '/tmp')}'")
    parts = a.data / "exports" / "reports" / "decision_A4_parts"
    parts.mkdir(exist_ok=True)

    def part(name: str) -> dict[str, Any]:
        return json.loads((parts / f"{name}.json").read_text())

    if a.part == "split":  # one process per part: the full-size split and the samples don't fit 6 GB together
        (parts / "split.json").write_text(json.dumps(identity_split(conn, a.data), indent=1))
    elif a.part == "recall":
        on, planted = recall(a.warehouse, splink=True)
        off, _ = recall(a.warehouse, splink=False)
        (parts / "recall.json").write_text(
            json.dumps({"on": on, "off": off, "planted": planted}, indent=1, default=str)
        )
    elif a.part == "embed":
        planted = part("recall")["planted"]
        (parts / "embed.json").write_text(json.dumps(embedding_matcher(conn, a.data, planted), indent=1))
    else:
        rec = part("recall")
        out: dict[str, Any] = {
            "generated": datetime.now(UTC).isoformat(timespec="minutes"),
            "warehouse": Path(a.warehouse).name,
            "identity": part("split"),
            "recall_with_splink": rec["on"],
            "recall_exact_only": rec["off"],
        }
        if (parts / "embed.json").exists():
            out["embedding"] = part("embed")
        out["figure"] = figure(out)
        path = a.data / "exports" / "reports" / "decision_A4.json"
        path.write_text(json.dumps(out, indent=1))
        print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
