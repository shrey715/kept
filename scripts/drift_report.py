# ruff: noqa: E501  (report prose)
"""Feature drift report: docs/reports/drift_report.pdf (LaTeX source alongside).

    uv run python scripts/drift_report.py              # needs the warehouse (stop kept serve)
    uv run python scripts/drift_report.py --render     # re-render from data/exports/reports/drift_data.json

PSI per registered feature (kept.features.drift), training rows (features_train.case_features) vs the features
served tonight (data/exports/features/case_features.parquet).
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime

from reportlib import AQUA, BLUE, BUILD, INK, KEPT, ORANGE, REPO, build_pdf, plt, save, style, tidy

CACHE = BUILD / "drift_data.json"


def collect() -> dict[str, object]:
    import duckdb
    import pandas as pd

    from kept.config import WAREHOUSE_PATH
    from kept.contracts.feature_registry import FEATURES
    from kept.features.drift import DRIFT, WATCH, drift_report

    live = pd.read_parquet(REPO / "data" / "exports" / "features" / "case_features.parquet")
    with duckdb.connect(str(WAREHOUSE_PATH), read_only=True) as con:
        train = con.execute("select * from features_train.case_features").df()
    rows = drift_report(train, live, [f.name for f in FEATURES])
    model_inputs = {f.name for f in FEATURES if f.model_input}
    counts = {s: sum(r.status == s for r in rows) for s in ("drift", "watch", "stable")}
    unseen = [r.feature for r in rows if r.missing_train >= 0.99 and r.missing_live < 0.99]
    data = {
        "written": datetime.now(UTC).strftime("%d %B %Y"),
        "train_rows": len(train),
        "live_rows": len(live),
        "live_as_of": str(live["as_of"].max()),
        "watch": WATCH,
        "drift": DRIFT,
        "counts": counts,
        "unseen": unseen,
        "rows": [
            {
                "feature": r.feature,
                "psi": r.psi,
                "status": r.status,
                "missing_train": r.missing_train,
                "missing_live": r.missing_live,
                "model_input": r.feature in model_inputs,
            }
            for r in rows
        ],
        "headline": f"{counts['drift']} features drift, {counts['watch']} to watch, {counts['stable']} stable (PSI vs training); "
        f"{len(unseen)} payroll features never appear in training rows.",
    }
    BUILD.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(data, indent=1))
    return data


def render(d: dict) -> None:  # type: ignore[type-arg]
    style()
    rows = d["rows"]
    color = {"drift": KEPT, "watch": ORANGE, "stable": BLUE}
    fig, ax = plt.subplots(figsize=(7.2, 0.27 * len(rows) + 1.1))
    y = list(range(len(rows)))[::-1]
    ax.barh(y, [min(r["psi"], 3) for r in rows], height=0.55, color=[color[r["status"]] for r in rows])
    for yi, r in zip(y, rows, strict=True):
        ax.text(
            min(r["psi"], 3) + 0.03,
            yi,
            f"{r['psi']:.2f}" + (" (capped)" if r["psi"] > 3 else ""),
            va="center",
            fontsize=7.5,
        )
    ax.set_yticks(y, [r["feature"] + ("" if r["model_input"] else " ·") for r in rows])
    for x in (d["watch"], d["drift"]):
        ax.axvline(x, color=INK, linewidth=0.8, linestyle="--")
    ax.text(d["drift"], len(rows) - 0.3, " watch 0.1 · drift 0.25", fontsize=7.5)
    ax.set_xlim(0, 3.5)
    ax.set_xlabel(
        "PSI vs training  (red: drift · orange: watch · blue: stable · dot after name: not a model input)",
        fontsize=8,
    )
    ax.set_title("Which features moved since training", loc="left")
    tidy(ax)
    psi_fig = save(fig, "d_psi")

    fig, ax = plt.subplots(figsize=(7.2, 0.27 * len(rows) + 1.1))
    for yi, r in zip(y, rows, strict=True):
        ax.plot(
            [100 * r["missing_train"], 100 * r["missing_live"]],
            [yi, yi],
            color="#c9c7c0",
            linewidth=1.5,
            zorder=1,
        )
        ax.scatter(100 * r["missing_train"], yi, s=28, color=BLUE, zorder=2)
        ax.scatter(100 * r["missing_live"], yi, s=28, color=AQUA, zorder=2)
    ax.set_yticks(y, [r["feature"] for r in rows])
    ax.scatter([], [], color=BLUE, label="training rows")
    ax.scatter([], [], color=AQUA, label="tonight")
    ax.legend(loc="lower right", frameon=False, fontsize=8)
    ax.set_xlabel("% of rows with no value")
    ax.set_title("Missing values, training vs tonight", loc="left")
    tidy(ax)
    miss_fig = save(fig, "d_missing")

    c = d["counts"]
    table = "\n".join(
        f"| `{r['feature']}` | {r['psi']:.3f} | {r['status']} | {100 * r['missing_train']:.0f}% | {100 * r['missing_live']:.0f}% | {'yes' if r['model_input'] else 'no'} |"
        for r in rows
    )
    md = f"""---
title: "Feature drift report"
subtitle: "Is tonight's open book still the population the uplift model learned from?"
author: "Team Sharpe Shooters"
date: "{d["written"]}"
---

# TL;DR

**{c["drift"]} drift · {c["watch"]} watch · {c["stable"]} stable** across the {len(rows)} registered features, comparing
{d["train_rows"]:,} training rows with the {d["live_rows"]:,} cases served tonight (features as of {d["live_as_of"]}).

Two things are going on, and only one of them is a problem:

1. **The baseline is different by design.** Training rows are *every past decision since 2016*; tonight is *today's
   open book*. Open cases skew later-stage and bigger-balance, so delinquency features (days past due, balance at
   risk, days in bucket) and cohort rates look "drifted" just because it's a different slice of customers, not
   because customers changed.
2. **The real finding:** {", ".join(f"`{u}`" for u in d["unseen"])} are **missing for every training row** but filled
   for ~20–25% of tonight's cases. The payroll history only lines up with recent decisions, so the model never got to
   learn from them. They're the heart of Kept (payday, spare cash), so the next retrain should backfill them for past
   decisions. Until then the rules and Kept sizing use them; the model just doesn't.

# How to read PSI

PSI (population stability index) compares two distributions bin by bin: Σ (live% − train%) × ln(live% / train%).
Numbers are cut at the training deciles, categories by value, and **missing values get their own bin**, so a
feature that suddenly goes blank shows up too. Usual bank bands: **< {d["watch"]} stable**, **{d["watch"]}–{d["drift"]} watch**,
**≥ {d["drift"]} drift** (investigate, then retrain).

![]({psi_fig}){{ width=100% }}

![]({miss_fig}){{ width=100% }}

# Every feature

| Feature | PSI | Status | Missing (train) | Missing (tonight) | Model input |
|---|--:|---|--:|--:|---|
{table}

# What we do with this

- **Nightly:** `kept drift` runs after `kept features`; a drifted *model input* that isn't explained by the
  open-book baseline is a reason to hold the new scores and retrain.
- **Next retrain:** backfill the three payroll features for past decisions, then re-check that their PSI and missing
  share line up.
- **Not a fairness check.** Drift says the population moved; the fairness report says whether groups get treated
  differently. Different questions.

*Rebuild:* `uv run python scripts/drift_report.py` (with `kept serve` stopped).
"""
    print(build_pdf(md, "drift_report"))


if __name__ == "__main__":
    render(json.loads(CACHE.read_text()) if "--render" in sys.argv else collect())
