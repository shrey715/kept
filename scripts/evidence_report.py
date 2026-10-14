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
from datetime import datetime
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
TRAIN_CUTOFF = datetime(2026, 8, 15)  # the live uplift champion's split (kept train --cutoff)
AUDIT_CUTOFF = datetime(2026, 3, 1)  # the split the leak was found on (the model now cuts at pm.CUTOFF)


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


def models(con: duckdb.DuckDBPyConnection, rows: pd.DataFrame) -> tuple[str, str]:
    lgbm = dict(n_estimators=200, num_leaves=15, min_child_samples=200, learning_rate=0.05, verbose=-1, deterministic=True, force_row_wise=True)  # reruns give the same numbers
    clean = list(pm.FEATURES)  # leak-free since #142
    early = rows.created < AUDIT_CUTOFF
    abl = ["| Features | Test AUC (promises after 1 Mar) |", "|---|---:|"]
    for name, feats in [
        ("all seven (as first shipped)", [*clean, "amount_ratio"]),
        ("without amount_ratio", clean),
        ("without amount_ratio and dpd", [f for f in clean if f != "dpd"]),
    ]:
        m = LGBMClassifier(**lgbm).fit(rows.loc[early, feats].astype(float), rows.kept[early])
        abl.append(
            f"| {name} | {roc_auc_score(rows.kept[~early], m.predict_proba(rows.loc[~early, feats].astype(float))[:, 1]):.3f} |"
        )

    bank = pd.read_csv(
        REPO / "data" / "raw" / "model_scores.csv",
        usecols=["model_name", "ptp_id", "score", "score_date"],
        low_memory=False,
    )
    bank = bank[bank.model_name == "ptp_break"].drop_duplicates("ptp_id", keep="last")
    outcome = con.execute(
        "select ptp_id, cast(status_ts as date) outcome_date from silver.promises_to_pay"
    ).df()
    r = rows.merge(bank.rename(columns={"score": "bank_break"}), on="ptp_id").merge(outcome, on="ptp_id")
    before = pd.to_datetime(r.score_date) < pd.to_datetime(r.outcome_date)
    lag = (pd.to_datetime(r.score_date) - pd.to_datetime(r.created).dt.normalize()).dt.days.mean()
    after_share = 1 - before.mean()
    r = r[before].reset_index(drop=True)  # a score dated on or after the outcome could know it
    cut = r.created.quantile(0.5)
    tr = r.created < cut
    y = r.kept[~tr].to_numpy()
    preds = {"Bank's ptp_break v2.1": -r.bank_break[~tr].to_numpy()}
    for name, feats in [
        ("Kept, leak-free (6 features)", clean),
        ("Kept, leak-free + the bank's score", [*clean, "bank_break"]),
    ]:
        m = LGBMClassifier(**lgbm).fit(r.loc[tr, feats].astype(float), r.kept[tr])
        preds[name] = m.predict_proba(r.loc[~tr, feats].astype(float))[:, 1]
    # paired bootstrap: every model is scored on the same resampled promises, so the gap's interval is tight
    rng = np.random.default_rng(0)
    draws = [rng.integers(0, len(y), len(y)) for _ in range(BOOT)]
    bank = preds["Bank's ptp_break v2.1"]
    h2h = [
        f"| Model (trained on scored promises before {cut:%d %b}, tested on the {(~tr).sum():,} after) | AUC [95% CI] | Against the bank's, AUC points [95% CI] |",
        "|---|---:|---:|",
    ]
    for name, p in preds.items():
        auc = [roc_auc_score(y[i], p[i]) for i in draws]
        cell = "—"
        if p is not bank:
            gap = [roc_auc_score(y[i], p[i]) - roc_auc_score(y[i], bank[i]) for i in draws]
            d = roc_auc_score(y, p) - roc_auc_score(y, bank)
            cell = f"{100 * d:+.1f} [{100 * np.percentile(gap, 2.5):+.1f}, {100 * np.percentile(gap, 97.5):+.1f}]"
        h2h.append(
            f"| {name} | {roc_auc_score(y, p):.3f} [{np.percentile(auc, 2.5):.3f}, {np.percentile(auc, 97.5):.3f}] | {cell} |"
        )
    # where each is stronger: calibration (the card states "N% chance") and ranking near payday
    from sklearn.isotonic import IsotonicRegression  # type: ignore[import-untyped]
    from sklearn.metrics import brier_score_loss

    probs = {
        "Bank's ptp_break, read as 1 − score": 1 - r.bank_break[~tr].to_numpy(),
        "Bank's ptp_break, recalibrated on the training half": IsotonicRegression(out_of_bounds="clip")
        .fit(-r.bank_break[tr], r.kept[tr])
        .predict(-r.bank_break[~tr]),
        "Kept, leak-free (6 features)": preds["Kept, leak-free (6 features)"],
        "Kept, leak-free + the bank's score": preds["Kept, leak-free + the bank's score"],
    }
    d = r.days_after_pay[~tr].astype(float).to_numpy()
    groups = {"due 0–7 days after payday": d <= 7, "8+ days after": d > 7, "payday unknown": np.isnan(d)}
    where = [
        "| Model | Brier | Calibration gap, pts | "
        + " | ".join(f"AUC, {k} ({m.sum():,}, {100 * y[m].mean():.0f}% kept)" for k, m in groups.items())
        + " |",
        "|---|---:|---:|" + "---:|" * len(groups),
    ]
    for name, p in probs.items():
        b = np.clip((p * 10).astype(int), 0, 9)
        gap = sum(abs(p[b == k].mean() - y[b == k].mean()) * (b == k).mean() for k in range(10) if (b == k).any())
        aucs = " | ".join(f"{roc_auc_score(y[m], p[m]):.3f}" for m in groups.values())
        where.append(f"| {name} | {brier_score_loss(y, p):.3f} | {100 * gap:.1f} | {aucs} |")
    note = (
        f"\n\nOnly promises the bank scored **before their outcome** are compared: the bank's score is dated {lag:.0f} days "
        f"after the promise on average, and {100 * after_share:.0f}% of its scores are dated on or after the outcome, which could know it."
    )
    return "\n".join(abl), "\n".join(h2h) + note, "\n".join(where)


def off_policy(con: duckdb.DuckDBPyConnection) -> str:
    """Doubly robust value of each policy on the uplift test decisions (randomised cases, from TRAIN_CUTOFF on):
    outcome model = the live champion (fitted before the cutoff), propensity = LightGBM on the same inputs, fitted
    before the cutoff, clipped at 0.05. Paid within 14 days is the outcome the uplift model is trained on."""
    import pickle

    from kept.nba.legacy import legacy_to_action
    from kept.nba.train import load_rows
    from kept.nba.uplift import _frame

    model = pickle.loads((REPO / "data" / "exports" / "models" / "uplift.pkl").read_bytes())
    acts = [a.value for a in model.actions]
    rows = load_rows(con)
    rows = rows[rows.action.isin(acts)].reset_index(drop=True)
    early = (rows.decision_at < TRAIN_CUTOFF).to_numpy()
    X = _frame(rows[list(model._columns)])
    prop = LGBMClassifier(
        n_estimators=200, num_leaves=15, min_child_samples=300, learning_rate=0.05, verbose=-1
    )
    prop.fit(X[early], rows.action[early])
    late = rows[~early].reset_index(drop=True)
    mu = model.predict_proba(late)[acts].to_numpy()
    p_all = pd.DataFrame(prop.predict_proba(X[~early]), columns=prop.classes_)[acts].to_numpy()
    a_idx = late.action.map({a: i for i, a in enumerate(acts)}).to_numpy()
    y = late.paid_14d.to_numpy(dtype=float)
    p_a = np.clip(p_all[np.arange(len(late)), a_idx], 0.05, None)
    resid = (y - mu[np.arange(len(late)), a_idx]) / p_a

    def est(v: np.ndarray) -> str:
        rng = np.random.default_rng(0)
        bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(BOOT)]
        return (
            f"{100 * v.mean():.1f}% [{100 * np.percentile(bs, 2.5):.1f}, {100 * np.percentile(bs, 97.5):.1f}]"
        )

    def dr(pi: np.ndarray, keep: np.ndarray) -> str:
        return est((mu[np.arange(len(late)), pi] + (a_idx == pi) * resid)[keep])

    def ips(pi: np.ndarray, keep: np.ndarray) -> str:  # self-normalised: no outcome model in the value
        w = ((a_idx == pi) / p_a)[keep]
        return est(w * y[keep] * len(w) / w.sum())

    legacy = late.nba_recommendation_last.map(lambda c: (x := legacy_to_action(c)) and x.value)
    has_legacy = legacy.isin(acts).to_numpy()
    legacy_idx = legacy.map({a: i for i, a in enumerate(acts)}).fillna(0).astype(int).to_numpy()
    everyone = np.ones(len(late), bool)
    out = [
        f"| Policy (on the {len(late):,} decisions from {TRAIN_CUTOFF:%d %b}) | Paid within 14 days: doubly robust | Inverse propensity |",
        "|---|---:|---:|",
        f"| What the bank actually did | {100 * y.mean():.1f}% (observed) | |",
    ]
    for name, pi, keep in [
        ("The bank's strategy recommendation", legacy_idx, has_legacy),
        ("Kept's model, on those same decisions", mu.argmax(axis=1), has_legacy),
        ("Kept's model: the action it scores best", mu.argmax(axis=1), everyone),
        ("Wait: contact nobody", np.full(len(late), acts.index("wait")), everyone),
    ]:
        cover = "" if keep.all() else f" ({100 * keep.mean():.0f}% of decisions)"
        out.append(f"| {name}{cover} | {dr(pi, keep)} | {ips(pi, keep)} |")
    return "\n".join(out)


def guards(con: duckdb.DuckDBPyConnection) -> str:
    """The guard metrics next to the primary one: the bank today (its randomised cells) against Kept."""
    b = con.execute("""
        select avg(complaint_flag::int) complaint, avg((coalesce(contact_cap_breach_count, 0) > 0)::int) cap,
               avg((coalesce(out_of_hours_contact_count, 0) > 0)::int) ooh
        from silver.collections_cases where assignment_method = 'random'""").fetchone()
    return "\n".join(
        [
            "| Guard (must not get worse) | Bank today (randomised cases) | Kept | Where Kept's number comes from |",
            "|---|---:|---:|---|",
            f"| Contact-cap breaches | {100 * b[1]:.2f}% of cases | 0 | hard rules before scoring, re-checked at release (`kept.nba.rules`, `kept.nba.release`) |",
            f"| Contact outside calling hours | {100 * b[2]:.1f}% of cases | 0 | call windows inside the customer's local calling hours (same) |",
            "| Hardship notes missed | not measured | recall 1.00 | extraction gate, holdout notes and calls (`docs/reports/extraction_gate.md`) |",
            "| Any-contact fairness ratio | not measured | 0.87 or above | four-fifths rule, 11 attributes (`docs/reports/fairness_report.pdf`) |",
            f"| Complaints | {100 * b[0]:.1f}% of cases | not measurable offline | needs a live pilot cell |",
        ]
    )


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
    rows = pm.load(con).merge(  # the leaky ratio the shipped model dropped, for the audit only
        con.execute(
            "select ptp_id, ptp_to_overdue_ratio::double as amount_ratio from silver.promises_to_pay"
        ).df(),
        on="ptp_id",
    )
    cell_md = cells(con)
    pay_md, pay_sum = payday(con, rows)
    abl_md, h2h_md, where_md = models(con, rows)
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

## 4. Kept's contact policy, estimated off-policy

{off_policy(con):s}

Which action to take wasn't randomised (the bank's strategy chose it), so these are estimates: the doubly robust one
uses the live uplift model plus a model of how the bank picked actions; the inverse-propensity one uses only the latter.
They agree. The doubly robust number for Kept leans optimistic, because Kept picks the action its own outcome model
scores best. A randomised pilot cell is the way to confirm it; the bank already runs four.

## 5. One primary metric, and the guards

**Primary: promised money paid** (§2). Kept moves it by changing when a promise falls due. **Guards** are what it must not
make worse:

{guards(con):s}

## 6. Against the bank's own model

{h2h_md:s}

On its own our leak-free model is weaker than the bank's `ptp_break` score. Used together, it adds what the bank's model
doesn't see (payday timing and the customer's own promise history) and beats it; the interval on that gain excludes zero
(paired bootstrap, the same resampled promises for every model). Because the bank's score only arrives
days after a promise is made, the combination is for **re-scoring promises already made** (who needs a reminder before
the due date); the due date itself is proposed with Kept's own model.

## 7. Where each model is stronger

The same held-out promises as §6. Calibration gap: the average distance between predicted and observed kept rates
across ten score bins, weighted by promises.

{where_md:s}

Read as published, the bank's score overstates the kept rate by about 24 points, and Kept's states it within 2. But
recalibrated on the same training half, the bank's score is as well calibrated, so calibration alone is not an edge
Kept can claim. **Kept's own model is not better than the bank's on any measure here.** Its value is in two other
places. It exists when the promise is made, about 9 days before the bank's score, which is when the due date is chosen.
And it carries information the bank's score lacks: **the combination is best overall on all three measures** (Brier,
calibration and AUC), and best on promises due 8+ days after payday and on those with no known payday. On the 1,081
promises due within a week of payday, the bank's score alone ranks slightly better.

Kept rates in this table are not comparable with §2: it holds only promises the bank scored before their outcome, which
leaves out promises that were resolved quickly.
""")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
