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

from reportlib import AQUA, BLUE, BUILD, INK, KEPT, ORANGE, REPO, plt, save, style, tidy

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
    save(fig, "d_psi")

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
    save(fig, "d_missing")

    print("figures written; compile with: uv run python scripts/reportlib.py")


if __name__ == "__main__":
    render(json.loads(CACHE.read_text()) if "--render" in sys.argv else collect())
