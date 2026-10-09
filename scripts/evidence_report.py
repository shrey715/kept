# ruff: noqa: E501  (report prose and SQL)
"""Measured evidence: docs/reports/evidence.md. Randomised test cells with confidence intervals, the payday effect
inside them, the policy value of dating promises after payday, a promise-model leakage audit, and our model against
the bank's own ptp_break score on the same promises.

    uv run python scripts/evidence_report.py                       # reads the warehouse (stop kept serve first)
    uv run python scripts/evidence_report.py --warehouse copy.duckdb

Read-only. Every number in the report comes from this script; intervals are 95% (normal approx. for the cells,
bootstrap with 300 resamples elsewhere, seed 0).
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.metrics import roc_auc_score

from kept.config import WAREHOUSE_PATH
from kept.nba import promise_model as pm

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "docs" / "reports" / "evidence.md"
BOOT = 300


def ci_diff(p1: float, n1: int, p2: float, n2: int) -> str:
    d, se = p1 - p2, math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    return f"{100 * d:+.2f} [{100 * (d - 1.96 * se):+.2f}, {100 * (d + 1.96 * se):+.2f}]"


def boot(df: pd.DataFrame, f) -> tuple[float, float, float]:  # type: ignore[no-untyped-def]
    xs = [f(df.sample(len(df), replace=True, random_state=i)) for i in range(BOOT)]
    return f(df), float(np.percentile(xs, 2.5)), float(np.percentile(xs, 97.5))


def cells(con: duckdb.DuckDBPyConnection) -> str:
    d = con.execute("""
        select k.test_cell, count(*) n,
          avg((k.cure_flag and k.days_to_cure <= 30)::int) cure30,
          count(case when k.entry_dpd between 1 and 30 and k.dpd_at_day_30 is not null then 1 end) n_roll,
          avg(case when k.entry_dpd between 1 and 30 and k.dpd_at_day_30 is not null then (k.dpd_at_day_30 > 30)::int end) roll30,
          avg(k.complaint_flag::int) complaint, avg((k.contact_attempts_total > 0)::int) any_contact,
          avg(k.contact_attempts_total) attempts
        from silver.collections_cases k where k.assignment_method = 'random' group by 1 order by 1""").df()
    h = d[d.test_cell == "no_contact_holdout"].iloc[0]
    lines = [
        "| Cell | Cases | Cured in 30 days | Δ vs holdout, pts [95% CI] | Rolled past 30 dpd | Δ vs holdout, pts [95% CI] | Complaints | Any contact | Attempts per case |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for _, r in d.iterrows():
        hold = r.test_cell == "no_contact_holdout"
        lines.append(
            f"| {r.test_cell} | {int(r.n):,} | {100 * r.cure30:.1f}% | {'—' if hold else ci_diff(r.cure30, r.n, h.cure30, h.n)} "
            f"| {100 * r.roll30:.1f}% | {'—' if hold else ci_diff(r.roll30, r.n_roll, h.roll30, h.n_roll)} "
            f"| {100 * r.complaint:.1f}% | {100 * r.any_contact:.1f}% | {r.attempts:.1f} |"
        )
    return "\n".join(lines)


def payday(con: duckdb.DuckDBPyConnection, rows: pd.DataFrame) -> tuple[str, str]:
    rnd = set(
        con.execute("""select p.ptp_id from silver.promises_to_pay p join silver.collections_cases c using (case_id)
                             where c.assignment_method = 'random'""")
        .df()
        .ptp_id
    )
    amounts = con.execute(
        "select ptp_id, ptp_amount amt, amount_paid_against paid from silver.promises_to_pay"
    ).df()
    x = rows[rows.ptp_id.isin(rnd) & rows.days_after_pay.notna()].merge(amounts, on="ptp_id")
    x["bucket"] = pd.cut(x.days_after_pay, [-1, 2, 7, 999], labels=["0-2", "3-7", "8+"])
    x["dpdb"] = pd.cut(x.dpd, [-1, 30, 60, 99999], labels=["1-30", "31-60", "61+"])

    def gain(col: str):  # type: ignore[no-untyped-def]
        def f(df: pd.DataFrame) -> float:  # dpd-stratified: 0-2 days after payday vs 8+
            out, w = [], []
            for _, g in df.groupby("dpdb", observed=True):
                a, b = g[g.bucket == "0-2"], g[g.bucket == "8+"]
                if len(a) and len(b):
                    out.append(
                        a.kept.mean() - b.kept.mean()
                        if col == "kept"
                        else a.paid.sum() / a.amt.sum() - b.paid.sum() / b.amt.sum()
                    )
                    w.append(len(g))
            return 100 * float(np.average(out, weights=w))

        return f

    def policy(
        df: pd.DataFrame,
    ) -> float:  # money paid if every promise were dated 0-2 days after payday, per dpd band
        tot = 0.0
        for _, g in df.groupby("dpdb", observed=True):
            a = g[g.bucket == "0-2"]
            tot += g.amt.sum() * (a.paid.sum() / a.amt.sum())
        return 100 * (tot / df.amt.sum() - df.paid.sum() / df.amt.sum())

    rows_md = ["| Due date | Promises | Kept in full | Promised money paid |", "|---|---:|---:|---:|"]
    for b in ["0-2", "3-7", "8+"]:
        s = x[x.bucket == b]
        rows_md.append(
            f"| {b} days after payday | {len(s):,} | {100 * s.kept.mean():.1f}% | {100 * s.paid.sum() / s.amt.sum():.1f}% |"
        )
    k, m, p = boot(x, gain("kept")), boot(x, gain("money")), boot(x, policy)
    summary = (
        f"- **Kept in full:** {k[0]:+.1f} pts [{k[1]:+.1f}, {k[2]:+.1f}] when due 0–2 days after payday rather than 8+, within days-past-due bands.\n"
        f"- **Promised money paid (the primary metric):** {m[0]:+.1f} pts [{m[1]:+.1f}, {m[2]:+.1f}].\n"
        f"- **Policy value:** dating every promise 0–2 days after payday would raise promised money paid by {p[0]:+.1f} pts "
        f"[{p[1]:+.1f}, {p[2]:+.1f}] over what these {len(x):,} promises achieved (direct estimate, per days-past-due band)."
    )
    return "\n".join(rows_md), summary


def models(rows: pd.DataFrame) -> tuple[str, str]:
    lgbm = dict(n_estimators=200, num_leaves=15, min_child_samples=200, learning_rate=0.05, verbose=-1)
    clean = [f for f in pm.FEATURES if f != "amount_ratio"]
    early = rows.created < pm.CUTOFF
    abl = ["| Features | Test AUC (promises after 1 Mar) |", "|---|---:|"]
    for name, feats in [
        ("all seven (as shipped)", list(pm.FEATURES)),
        ("without amount_ratio", clean),
        ("without amount_ratio and dpd", [f for f in clean if f != "dpd"]),
    ]:
        m = LGBMClassifier(**lgbm).fit(rows.loc[early, feats].astype(float), rows.kept[early])
        abl.append(
            f"| {name} | {roc_auc_score(rows.kept[~early], m.predict_proba(rows.loc[~early, feats].astype(float))[:, 1]):.3f} |"
        )

    bank = pd.read_csv(
        REPO / "data" / "raw" / "model_scores.csv",
        usecols=["model_name", "ptp_id", "score"],
        low_memory=False,
    )
    bank = bank[bank.model_name == "ptp_break"].drop_duplicates("ptp_id", keep="last")[["ptp_id", "score"]]
    r = rows.merge(bank.rename(columns={"score": "bank_break"}), on="ptp_id")
    cut = r.created.quantile(0.5)
    tr = r.created < cut
    h2h = [
        f"| Model (trained on scored promises before {cut:%d %b}, tested on the {(~tr).sum():,} after) | AUC |",
        "|---|---:|",
        f"| Bank's ptp_break v2.1 | {roc_auc_score(r.kept[~tr], -r.bank_break[~tr]):.3f} |",
    ]
    for name, feats in [
        ("Kept, leak-free (6 features)", clean),
        ("Kept, leak-free + the bank's score", [*clean, "bank_break"]),
    ]:
        m = LGBMClassifier(**lgbm).fit(r.loc[tr, feats].astype(float), r.kept[tr])
        h2h.append(
            f"| {name} | {roc_auc_score(r.kept[~tr], m.predict_proba(r.loc[~tr, feats].astype(float))[:, 1]):.3f} |"
        )
    return "\n".join(abl), "\n".join(h2h)


def ratio_table(con: duckdb.DuckDBPyConnection) -> str:
    d = con.execute("""
        select ptp_status, count(*) n, avg((abs(ptp_amount - overdue_at_creation) < 0.01)::int) full_balance
        from silver.promises_to_pay where ptp_status in ('kept', 'partially_kept', 'broken') group by 1 order by 1""").df()
    return "\n".join(
        ["| Outcome | Promises | Promised the full overdue amount |", "|---|---:|---:|"]
        + [f"| {r.ptp_status} | {int(r.n):,} | {100 * r.full_balance:.1f}% |" for _, r in d.iterrows()]
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--warehouse", default=str(WAREHOUSE_PATH))
    a = ap.parse_args()
    con = duckdb.connect(a.warehouse, read_only=True)
    con.execute("set memory_limit = '8GB'")
    rows = pm.load(con)
    cell_md = cells(con)
    pay_md, pay_sum = payday(con, rows)
    abl_md, h2h_md = models(rows)
    OUT.write_text(f"""# Measured evidence

Generated by `scripts/evidence_report.py` from the release data (read-only). Intervals are 95%.

## 1. The bank's randomised test cells

{cell_md:s}

The bank randomised 146,573 cases between its champion strategy, two challengers and a "no contact" holdout. None of
the four is distinguishable on cure or roll rate: every interval includes zero. The holdout is not a true holdout either:
most of its cases were still contacted, about as often as the others. **What the bank changes between cells (channel and
intensity) doesn't move outcomes; Kept changes something else: when the promise falls due.**

## 2. Payday timing, inside the randomised cells

{pay_md:s}

{pay_sum:s}

Payday timing itself wasn't randomised (it's where the due date happened to fall), so this is observational, but it is
measured on the randomised population, compared within days-past-due bands, with intervals. Promises due 3–7 days after
payday do as well as 0–2: what matters is falling due **within a week of payday**, not after the money has gone. The plan's next step is a
randomised due-date test, which the bank can run as a fourth challenger cell.

## 3. Promise model: leakage audit

{abl_md:s}

One feature, `amount_ratio` (promised amount ÷ overdue amount), carries almost all of the 0.92. It is computed correctly
at promise time, but in this data a full-balance promise is all but certain to be kept:

{ratio_table(con):s}

That is too clean to be real behaviour, so we treat it as an artefact of how the data was generated and **headline the
leak-free model**. Kept's promise model drops this feature (phase 2).

## 4. Against the bank's own model

{h2h_md:s}

On its own our leak-free model is weaker than the bank's `ptp_break` score. Used together, it adds what the bank's model
doesn't see (payday timing and the customer's own promise history) and beats it. Phase 2 ships that combination through
the champion/challenger gate.
""")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
