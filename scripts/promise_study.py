# ruff: noqa: E501  (report prose)
"""The promise model: its calibration against the fall in the kept rate, and which inputs of the wide model (evidence.md §8)
a serving path could supply. Writes docs/reports/promise_model_study.md and data/exports/reports/promise_study.json.

    uv run python scripts/promise_study.py [--warehouse data/warehouse/kept.duckdb]

Calibration: the recipe (trees fitted up to `calibrate_days` before the cutoff, a calibrator on those days) is chosen on a
validation window (15 Jun to 15 Jul), then the held-out window (from 15 Jul, the model card's) is scored once.
Wide model: the §8 model (79 inputs, LightGBM, recent promises weighted, same split, same test promises as the bank's score),
and subsets of its inputs by where they would come from.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.metrics import roc_auc_score  # type: ignore[import-untyped]

from kept.config import WAREHOUSE_PATH
from kept.nba import promise_model as pm

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import evidence_report as ev  # noqa: E402  (the §8 SQL and settings)

OUT_MD, OUT_JSON = REPO / "docs" / "reports" / "promise_model_study.md", REPO / "data" / "exports" / "reports" / "promise_study.json"
VALID = (datetime(2026, 6, 15), datetime(2026, 7, 15))  # validation: calibrate to 15 Jun, score 15 Jun to 15 Jul
RECIPES = {  # name: (calibrate_days, method)
    "isotonic, 60 days (before)": (60, "isotonic"),
    "isotonic, 30 days": (30, "isotonic"),
    "logistic, 60 days": (60, "platt"),
    "logistic, 30 days": (30, "platt"),
    "logistic, 21 days": (21, "platt"),
    "logistic, 14 days (shipped)": (14, "platt"),
}


def calibration(rows: pd.DataFrame) -> dict[str, object]:
    out: dict[str, object] = {"validation": {}, "held_out": {}}
    v_rows = rows[(rows.created < VALID[1])]
    for name, (days, method) in RECIPES.items():
        _, m = pm.train(v_rows, cutoff=VALID[0], calibrate_days=days, method=method)
        out["validation"][name] = m  # type: ignore[index]
    for name, (days, method) in (("before", RECIPES["isotonic, 60 days (before)"]), ("after", RECIPES["logistic, 14 days (shipped)"])):
        model, m = pm.train(rows, cutoff=pm.CUTOFF, calibrate_days=days, method=method)
        test = rows[rows.created >= pm.CUTOFF]
        p, y = model.p_kept(test.to_dict("records")), test.kept.to_numpy()
        b = np.clip((p * 10).astype(int), 0, 9)
        bands = [
            {"predicted": float(p[b == k].mean()), "observed": float(y[b == k].mean()), "n": int((b == k).sum())}
            for k in range(10)
            if (b == k).sum() >= 200
        ]
        mon = test.created.dt.to_period("M").astype(str).to_numpy()
        months = {x: {"predicted": float(p[mon == x].mean()), "observed": float(y[mon == x].mean()), "n": int((mon == x).sum())} for x in sorted(set(mon))}
        out["held_out"][name] = {**m, "bands": bands, "months": months}  # type: ignore[index]
    return out


def wide(con: duckdb.DuckDBPyConnection, rows: pd.DataFrame) -> dict[str, object]:
    w = con.execute(ev.SQL_WIDE).df().merge(con.execute(ev.SQL_HISTORY).df(), on="ptp_id")
    r = rows.merge(w, on="ptp_id").sort_values(["created", "ptp_id"]).reset_index(drop=True)
    for c in ev.CATEGORIES:
        r[c] = r[c].astype("category")
    feats = [*pm.FEATURES, *(c for c in w.columns if c != "ptp_id")]
    bank = pd.read_csv(REPO / "data" / "raw" / "model_scores.csv", usecols=["model_name", "ptp_id", "score", "score_date"], low_memory=False)
    bank = bank[bank.model_name == "ptp_break"].drop_duplicates("ptp_id", keep="last")
    dates = con.execute("select ptp_id, cast(status_ts as date) od, ptp_due_date due from silver.promises_to_pay").df()
    h = r.merge(bank, on="ptp_id").merge(dates, on="ptp_id")
    h = h[pd.to_datetime(h.score_date) < pd.to_datetime(h.od)].reset_index(drop=True)  # as evidence.md §6, §8
    cut = h.created.quantile(0.5)
    test, fit = h[h.created >= cut].reset_index(drop=True), (r.created < cut).to_numpy()
    wt = 0.5 ** ((cut - r.created).dt.days.to_numpy() / ev.HALF_LIFE_DAYS)

    def auc(cols: list[str]) -> float:
        m = LGBMClassifier(**ev.GBM_WIDE).fit(r.loc[fit, cols], r.kept[fit], sample_weight=wt[fit])
        return float(roc_auc_score(test.kept, m.predict_proba(test[cols])[:, 1]))

    base, extra = list(pm.FEATURES), set(feats) - set(pm.FEATURES)
    groups = {
        "balance, contacts and payroll (the case features Kept already serves, in the wide model's own definitions)": ["lod", "n30", "rpc30", "n7", "pay_days_since", "pay_delay", "pay_change", "pay_gaps3"],
        "monthly account snapshots (utilisation, payment cover, balance and delinquency slopes)": ["util", "paycov", "sal", "ovl", *[c for c in extra if c.startswith("s_")]],
        "card statements": [c for c in extra if c.startswith("c_")],
        "deposit transactions, last 45 days (without the benefits category, a proxy)": ["in30", "out30", "hcl30", "pay30", "minbal30", "lastbal", "debt30", "since_pay", "net30", "od_in"],
        "customer record (tenure, declared income, employment, income verified)": ["tenure_d", "inc", "emp", "iv"],
        "loan instalments": [c for c in extra if c.startswith("l_")],
        "bureau pull": ["rs", "ru", "dt", "inq", "rsd"],
        "promise details and history, month and weekday": ["ptp_channel", "ptp_type", "product", "payment_method_promised", "rem", "sid_gap", "seq", "pbc", "mon", "wd", *[c for c in extra if c.startswith("p_")]],
    }
    res: dict[str, object] = {"promises_test": len(test), "promises_fit": int(fit.sum()), "wide_all": auc(feats), "six": auc(base), "marginal": {}, "cumulative": {}}
    for name, g in groups.items():
        res["marginal"][name] = auc(base + g)  # type: ignore[index]
    used: list[str] = []
    for name in list(groups)[:5]:  # the order a plumbing job would follow: cheapest first
        used += groups[name]
        res["cumulative"][name] = {"n_inputs": len(base) + len(used), "auc": auc(base + used)}  # type: ignore[index]
    return res


def markdown(c: dict, wd: dict) -> str:  # type: ignore[type-arg]
    v, ho = c["validation"], c["held_out"]
    pts = lambda x: f"{100 * x:+.1f}"  # noqa: E731
    md = [
        "# The promise model: calibration, and what a wider model needs\n",
        "Written by `scripts/promise_study.py`. Intervals and settings as in `evidence.md` §8. Nothing here is tuned on the held-out window.\n",
        "## Calibration\n",
        "The kept rate fell from about 63% to about 35% between April and August 2026 and the trees were fitted on the long history, so the card's \"N% chance it's kept\" was too high. "
        f"Recipes compared on a validation window (calibrate to {VALID[0]:%d %b}, score {VALID[0]:%d %b} to {VALID[1]:%d %b}); the kept rate was still falling in it:\n",
        "| Recipe | Mean predicted minus observed, points | Worst band gap, points | Brier |",
        "|---|---:|---:|---:|",
        *[f"| {n} | {pts(m['calibration_mean_gap'])} | {100 * m['calibration_max_gap']:.1f} | {m['brier']:.3f} |" for n, m in v.items()],
        "",
        f"The shortest window wins on the validation window, so the shipped recipe is a logistic map on the last 14 days. Held-out window (promises from {pm.CUTOFF:%d %b %Y}), scored once:\n",
        "| | Mean predicted minus observed, points | Worst band gap, points | Brier | AUC |",
        "|---|---:|---:|---:|---:|",
        *[f"| {n} ({'isotonic, 60 days' if n == 'before' else 'logistic, 14 days'}) | {pts(m['calibration_mean_gap'])} | {100 * m['calibration_max_gap']:.1f} | {m['brier']:.3f} | {m['auc']:.3f} |" for n, m in ho.items()],
        "",
        "By band, held-out (predicted / observed, promises):\n",
        "| Before | After |",
        "|---|---|",
    ]
    nb = max(len(ho["before"]["bands"]), len(ho["after"]["bands"]))
    cell = lambda bs, i: f"{100 * bs[i]['predicted']:.1f}% / {100 * bs[i]['observed']:.1f}% ({bs[i]['n']:,})" if i < len(bs) else ""  # noqa: E731
    md += [f"| {cell(ho['before']['bands'], i)} | {cell(ho['after']['bands'], i)} |" for i in range(nb)]
    md += [
        "",
        "By month of the promise, held-out (predicted / observed):\n",
        "| Month | Before | After |",
        "|---|---|---|",
        *[f"| {k} | {100 * m['predicted']:.1f}% / {100 * m['observed']:.1f}% | {100 * ho['after']['months'][k]['predicted']:.1f}% / {100 * ho['after']['months'][k]['observed']:.1f}% |" for k, m in ho["before"]["months"].items()],
        "",
        "What is left is not the level but the shape: since the fall, promises due soon are kept more than the trees expect and promises due in a month less (days to due flattened), which a two-number map cannot follow. Retraining the trees on the recent regime only, or weighting recent promises, scored worse (AUC 0.56 to 0.60 against 0.62 on the validation window), so the trees are unchanged. "
        "`kept train-promises --cutoff <date>` moves the calibration window forward as promises resolve; it is not a nightly step.\n",
        "## The wide model, and what serving can supply\n",
        f"The §8 model (79 inputs) on the same split: AUC **{wd['wide_all']:.3f}** on {wd['promises_test']:,} test promises; the six inputs the card uses, fitted the same way: **{wd['six']:.3f}**. A subset ships only if it keeps most of that gain ({wd['wide_all'] - wd['six']:.3f}).\n",
        "Each group added to the six alone:\n",
        "| Group | AUC | Share of the gain |",
        "|---|---:|---:|",
        *[f"| {n} | {a:.3f} | {100 * (a - wd['six']) / (wd['wide_all'] - wd['six']):.0f}% |" for n, a in wd["marginal"].items()],
        "",
        "Cumulatively, cheapest first:\n",
        "| Inputs | Count | AUC | Share of the gain |",
        "|---|---:|---:|---:|",
        *[f"| {n} | {x['n_inputs']} | {x['auc']:.3f} | {100 * (x['auc'] - wd['six']) / (wd['wide_all'] - wd['six']):.0f}% |" for n, x in wd["cumulative"].items()],
        "",
        "**Not shipped.** What `FeatureVector` carries today reaches under half of the gain (first row above). Most of it needs inputs the serving path does not have: the point-in-time features for a promise are not the point-in-time features for a decision, so they need their own dbt spine (one row per promise at its creation, the training side) and the same SQL at `as_of` for the cases being proposed a promise (the serving side), then registry entries, `FeatureVector` fields, Feast and parity for each, as the ten context inputs got. The monthly account snapshots are the piece that matters (the cumulative table): with them the model keeps most of the gain; the rest adds a few points of it each. The card's sentence would not change. Excluded on purpose: the deposit-transaction benefits category (a proxy for benefit receipt) and anything on the contract's protected or proxy lists.\n",
    ]
    return "\n".join(md)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--warehouse", default=str(WAREHOUSE_PATH))
    ap.add_argument("--report-only", action="store_true")
    args = ap.parse_args()
    if args.report_only:
        d = json.loads(OUT_JSON.read_text())
    else:
        con = duckdb.connect(args.warehouse, read_only=True)
        con.execute("set memory_limit = '3GB'")
        rows = pm.load(con)
        d = {"calibration": calibration(rows), "wide": wide(con, rows)}
        OUT_JSON.write_text(json.dumps(d, indent=1))
    OUT_MD.write_text(markdown(d["calibration"], d["wide"]))
    print(f"wrote {OUT_MD}")


if __name__ == "__main__":
    main()
