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
EV: dict[str, object] = {}  # the headline numbers, for the decks (data/exports/reports/evidence.json)
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
    EV.update(payday_kept=k, payday_money=m, payday_policy=p, payday_promises=len(x))
    summary = (
        f"- **Kept in full:** {k[0]:+.1f} pts [{k[1]:+.1f}, {k[2]:+.1f}] when due 0–2 days after payday rather than 8+, within days-past-due bands.\n"
        f"- **Promised money paid (the primary metric):** {m[0]:+.1f} pts [{m[1]:+.1f}, {m[2]:+.1f}].\n"
        f"- **Policy value:** dating every promise 0–2 days after payday would raise promised money paid by {p[0]:+.1f} pts "
        f"[{p[1]:+.1f}, {p[2]:+.1f}] over what these {len(x):,} promises achieved (direct estimate, per days-past-due band)."
    )
    return "\n".join(rows_md), summary


def _signed_payday(con: duckdb.DuckDBPyConnection, shift: int = 0) -> pd.DataFrame:
    """Resolved promises with x = signed days from the nearest recorded payday (0 = due on payday, < 0 before it).
    shift moves every payday by that many days (the placebo)."""
    d = con.execute(f"""
        with pr as (select ptp_id, crm_customer_id, ptp_due_date due, (ptp_status = 'kept')::int kept,
                           ptp_amount::double amt, coalesce(amount_paid_against, 0)::double paid, dpd_at_creation dpd
                    from silver.promises_to_pay where ptp_status in ('kept', 'partially_kept', 'broken')),
        pay as (select distinct crm_customer_id, unnest([first_credit_date, last_credit_date]) + {int(shift)} as d
                from silver.salary_credit_history where crm_customer_id is not null),
        lst as (select p.ptp_id, max(y.d) lp from pr p join pay y on y.crm_customer_id = p.crm_customer_id
                and y.d between p.due - 40 and p.due group by 1),
        nxt as (select p.ptp_id, min(y.d) np from pr p join pay y on y.crm_customer_id = p.crm_customer_id
                and y.d > p.due and y.d <= p.due + 40 group by 1)
        select p.*, p.due - l.lp aft, n.np - p.due bef from pr p join lst l using (ptp_id) join nxt n using (ptp_id)
        order by ptp_id""").df()
    return d.assign(x=np.where(d.aft <= d.bef, d.aft, -d.bef), dpdb=pd.cut(d.dpd, [-1, 30, 60, 99999], labels=False))


def payday_designs(con: duckdb.DuckDBPyConnection) -> tuple[str, str]:
    """Three checks that the §2 effect is the payday: a sharp comparison around it, the same customer on and off it,
    and fake paydays."""
    d = _signed_payday(con)

    def gap(df: pd.DataFrame, a: pd.Series, b: pd.Series, money: bool = False) -> float:  # within dpd bands
        out, w = [], []
        for _, g in df.groupby("dpdb"):
            A, B = g[a.loc[g.index]], g[b.loc[g.index]]
            if len(A) and len(B):
                out.append(A.paid.sum() / A.amt.sum() - B.paid.sum() / B.amt.sum() if money else A.kept.mean() - B.kept.mean())
                w.append(len(g))
        return 100 * float(np.average(out, weights=w))

    def ci(df: pd.DataFrame, f, cluster: bool = False, key: str | None = None) -> str:  # type: ignore[no-untyped-def]
        rng = np.random.default_rng(0)
        if cluster:  # resample customers, not promises
            grp = df.groupby("crm_customer_id").indices
            ids = np.array(list(grp))
            xs = [f(df.iloc[np.concatenate([grp[i] for i in rng.choice(ids, len(ids))])].reset_index(drop=True)) for _ in range(BOOT)]
        else:
            xs = [f(df.iloc[rng.integers(0, len(df), len(df))].reset_index(drop=True)) for _ in range(BOOT)]
        v = (f(df), float(np.percentile(xs, 2.5)), float(np.percentile(xs, 97.5)))
        if key:
            EV[key] = v
        return f"{v[0]:+.1f} [{v[1]:+.1f}, {v[2]:+.1f}]"

    near = d[d.x.between(-3, 3)]
    by_day = near.groupby("x").agg(n=("kept", "size"), kept=("kept", "mean"), paid=("paid", "sum"), amt=("amt", "sum"))
    day_md = "\n".join(
        ["| Due, days from payday | " + " | ".join(f"{x:+d}" if x else "on payday" for x in by_day.index) + " |",
         "|---|" + "---:|" * len(by_day),
         "| Promises | " + " | ".join(f"{n:,}" for n in by_day.n) + " |",
         "| Kept in full | " + " | ".join(f"{100 * k:.1f}%" for k in by_day.kept) + " |",
         "| Promised money paid | " + " | ".join(f"{100 * p / a:.1f}%" for p, a in zip(by_day.paid, by_day.amt, strict=True)) + " |"]
    )

    def on_vs(lo: int, hi: int, money: bool = False):  # type: ignore[no-untyped-def]
        return lambda df: gap(df, df.x == 0, df.x.between(lo, hi), money)

    def within(df: pd.DataFrame) -> float:  # customer fixed effects: kept on "due on payday", dpd bands as controls
        on = (df.x == 0).astype(float)
        keep = on.groupby(df.crm_customer_id).transform("std") > 0
        df, on = df[keep], on[keep]
        dm = lambda v: v - v.groupby(df.crm_customer_id).transform("mean")  # noqa: E731
        bands = pd.get_dummies(df.dpdb, prefix="b").astype(float).iloc[:, 1:]
        X = np.column_stack([dm(on), *(dm(bands[c]) for c in bands)])
        return 100 * float(np.linalg.lstsq(X, dm(df.kept.astype(float)), rcond=None)[0][0])

    both = d[(d.x == 0).groupby(d.crm_customer_id).transform("std") > 0]
    real = d.set_index("ptp_id").x
    placebo = []
    for shift in (-10, -5, -3, 3, 5, 10):
        p = _signed_payday(con, shift)
        p = p[~p.ptp_id.map(real).abs().isin([0, 7, 14])].reset_index(drop=True)  # no real paydays in either group
        placebo.append(f"{shift:+d} days: {ci(p, lambda df: gap(df, df.x == 0, df.x.between(-3, -1) | df.x.between(1, 3)), key=f"placebo_{shift}")}")
    rows_md = "\n".join([
        "| Check | Kept in full, pts [95% CI] | Promised money paid, pts [95% CI] |",
        "|---|---:|---:|",
        f"| Due on payday against 1–3 days before | {ci(d, on_vs(-3, -1), key="on_vs_before")} | {ci(d, on_vs(-3, -1, True))} |",
        f"| Due on payday against 1–3 days after | {ci(d, on_vs(1, 3), key="on_vs_after")} | {ci(d, on_vs(1, 3, True))} |",
        f"| The same customer, on payday against not ({both.crm_customer_id.nunique():,} customers, {len(both):,} promises) | {ci(both, within, cluster=True, key="within_customer")} | |",
    ])
    return day_md, rows_md + "\n\nFake paydays (every payday moved, promises due near a real payday removed), on the fake payday against 1–3 days either side: " + "; ".join(placebo) + "."


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
    """Kept's contact policy against what the bank actually did, on the uplift test decisions (randomised cases, from
    TRAIN_CUTOFF on). Kept's policy: the action the live champion scores best (fitted before the cutoff). Value: doubly robust,
    outcome models per action and a multinomial propensity cross-fitted by case (`kept.nba.causal.policy_value`), on rows where
    the bank's chance of Kept's action is in [0.05, 0.95]; the bank's value is the observed mean on the same rows. 95% intervals
    resample whole cases. The bank's own recommendation field is not used: it is look-ahead (docs/reports/uplift_improvement.md)."""
    import pickle

    from kept.contracts.feature_registry import model_inputs
    from kept.nba.causal import CLIP, case_bootstrap, policy_value
    from kept.nba.train import CONTEXT_COLS, load_rows

    model = pickle.loads((REPO / "data" / "exports" / "models" / "uplift.pkl").read_bytes())
    rows = load_rows(con, extras=True)
    for c in ("last_rpc", "last_ptp_made"):
        rows[c] = rows[c].astype(float)
    cols = [*model_inputs(), *CONTEXT_COLS]
    late = (rows.decision_at >= TRAIN_CUTOFF).to_numpy()
    pi = np.full(len(rows), "wait", dtype=object)
    pi[late] = model.predict_proba(rows[late][list(model._columns)]).idxmax(axis=1).to_numpy()
    rows["pi"] = pi
    known = rows.paid_14d_known.to_numpy(bool)
    clean = rows.covered.to_numpy(bool)

    def run(label: str, outcome: str, keep: np.ndarray) -> dict[str, object]:
        d = rows[keep].reset_index(drop=True)
        v = policy_value(d, cols, d.pi.to_numpy(), outcome, evaluate=(d.decision_at >= TRAIN_CUTOFF).to_numpy())
        ok = ((v.e_pi >= CLIP[0]) & (v.e_pi <= CLIP[1])).to_numpy()
        t = d.loc[v.index[ok]]
        psi, y = v.psi.to_numpy()[ok], v.y.to_numpy()[ok]

        def ci(f) -> tuple[float, float, float]:  # type: ignore[no-untyped-def]
            bs = case_bootstrap(t.case_id, f, reps=BOOT)
            return float(f(np.ones(len(t)))), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))

        gap = ci(lambda w: 1000 * (w * (psi - y)).sum() / w.sum())
        return {
            "label": label, "decisions": len(v), "kept_rows": int(ok.sum()), "share_kept": float(ok.mean()),
            "bank": ci(lambda w: 100 * (w * y).sum() / w.sum()), "kept": ci(lambda w: 100 * (w * psi).sum() / w.sum()),
            "gap_per_1000": gap, "share_changed": float((t.pi != v.a.to_numpy()[ok]).mean()),
        }  # fmt: skip

    res = [
        run("Clean outcome: account-sourced payments, covered cases", "paid_clean_14d", clean),
        run("Same rows, old label (payments flagged on the contact row included)", "paid_14d", clean & known),
        run("Old label, every decision with a known outcome (as first published)", "paid_14d", known),
    ]
    EV["offpolicy_per_1000"] = res[0]["gap_per_1000"]  # the headline: clean outcome, overlap rows
    EV["offpolicy_old_label_per_1000"] = res[1]["gap_per_1000"]  # same rows, old label
    EV["offpolicy_runs"] = res
    out = [
        f"| Kept's model against what the bank did (decisions from {TRAIN_CUTOFF:%d %b}) | Decisions kept | Bank, observed | Kept, doubly robust | Kept minus bank, per 1,000 decisions [95% CI] | Actions changed |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    def sg(x: float) -> str:  # signed, and no "-0"
        return "0" if round(x) == 0 else f"{x:+.0f}"

    for r in res:
        b, k_, g = r["bank"], r["kept"], r["gap_per_1000"]
        out.append(
            f"| {r['label']} | {r['kept_rows']:,} of {r['decisions']:,} ({100 * r['share_kept']:.0f}%) | {b[0]:.1f}% [{b[1]:.1f}, {b[2]:.1f}] "
            f"| {k_[0]:.1f}% [{k_[1]:.1f}, {k_[2]:.1f}] | **{sg(g[0])}** [{sg(g[1])}, {sg(g[2])}] | {100 * r['share_changed']:.0f}% |"
        )
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


SQL_CELLS = """
select k.case_id, k.case_open_date, k.test_cell <> 'no_contact_holdout' as worked,
       (k.cure_flag and k.days_to_cure <= 30)::int * k.entry_overdue::double as cured_dollars,
       k.entry_dpd, ln(1 + k.entry_overdue::double) log_overdue, k.accounts_in_case_count, k.prior_cases_12m,
       k.primary_product, k.case_open_reason, k.province_code, k.language_of_service,
       date_diff('day', u.since, k.case_open_date) tenure_d, u.inc, u.emp
from silver.collections_cases k
left join (select crm_customer_id, any_value(customer_since_date) since, any_value(declared_annual_income)::double inc,
                  any_value(employment_status) emp from silver.customers group by 1) u
    on u.crm_customer_id = k.coll_customer_ref
where k.assignment_method = 'random' and coalesce(k.outcome, '') <> ''"""


def cell_uplift(con: duckdb.DuckDBPyConnection) -> str:
    """An uplift model on the one thing the bank randomised: worked by a strategy cell or held out. Outcome: overdue
    dollars cured within 30 days. Fit on the first 70% of cases by open date, valued on the rest."""
    d = con.execute(SQL_CELLS).df()
    for c in ("primary_product", "case_open_reason", "province_code", "language_of_service", "emp"):
        d[c] = d[c].astype("category")
    feats = [c for c in d.columns if c not in ("case_id", "case_open_date", "worked", "cured_dollars")]
    d = d.sort_values(["case_open_date", "case_id"]).reset_index(drop=True)
    fit = np.arange(len(d)) < int(0.7 * len(d))
    from lightgbm import LGBMRegressor

    arms = {}
    for w in (True, False):
        m = fit & (d.worked == w).to_numpy()
        arms[w] = LGBMRegressor(n_estimators=300, num_leaves=15, min_child_samples=200, learning_rate=0.03, verbose=-1,
                                deterministic=True, force_row_wise=True).fit(d.loc[m, feats], d.cured_dollars[m])
    t = d[~fit].reset_index(drop=True)
    score = arms[True].predict(t[feats]) - arms[False].predict(t[feats])
    y, w = t.cured_dollars.to_numpy(), t.worked.to_numpy()

    def lift(idx: np.ndarray, top: float) -> float:  # worked minus held out, per case, among the top share by score
        s, yy, ww = score[idx], y[idx], w[idx]
        k = s >= np.quantile(s, 1 - top)
        return float(yy[k & ww].mean() - yy[k & ~ww].mean())

    rng = np.random.default_rng(0)
    draws = [rng.integers(0, len(t), len(t)) for _ in range(BOOT)]
    everyone = np.arange(len(t))
    rows_md = [
        f"| Cases worked (held-out {len(t):,} cases, {int((~w).sum()):,} of them held out) | Overdue dollars cured in 30 days, worked minus held out, per 1,000 cases [95% CI] |",
        "|---|---:|",
    ]
    for top in (1.0, 0.5, 0.3, 0.1):
        v = lift(everyone, top)
        bs = [lift(i, top) for i in draws]
        EV[f"cell_top{int(top * 100)}"] = (1000 * v, 1000 * float(np.percentile(bs, 2.5)), 1000 * float(np.percentile(bs, 97.5)))
        label = "Everyone (what the bank does)" if top == 1.0 else f"The top {top:.0%} by the model's uplift"
        rows_md.append(
            f"| {label} | ${1000 * v:+,.0f} [${1000 * np.percentile(bs, 2.5):+,.0f}, ${1000 * np.percentile(bs, 97.5):+,.0f}] |"
        )
    return "\n".join(rows_md)


SQL_WIDE = """
with p as (select ptp_id, crm_customer_id, ptp_created_ts c, ptp_due_date due, ptp_channel, ptp_type, product,
                  payment_method_promised, ptp_sequence_in_case seq, prior_broken_ptp_count pbc,
                  overdue_at_creation::double overdue, customer_stated_income_date sid, reminder_scheduled_flag rem
           from silver.promises_to_pay where ptp_status in ('kept','partially_kept','broken')),
ch as (select p.ptp_id, count(*) n30, sum(rpc_flag::int) rpc30, avg((direction='inbound')::int) inb30,
              count(*) filter (where h.contact_ts_utc > p.c - interval 7 day) n7
       from p join silver.contact_history h on h.crm_customer_id = p.crm_customer_id
        and h.contact_ts_utc < p.c and h.contact_ts_utc >= p.c - interval 30 day group by 1),
sn as (select p.ptp_id, sum(s.balance) bal, sum(s.limit_or_original_amount) lim, sum(s.payment_made) pay,
              sum(s.minimum_due) mind, max(s.salary_credit_amount) sal, max(s.overlimit_flag::int) ovl
       from p join silver.account_monthly_snapshot s on s.crm_customer_id = p.crm_customer_id
        and s.month_end_date = (select max(month_end_date) from silver.account_monthly_snapshot s2
              where s2.crm_customer_id = p.crm_customer_id and s2.month_end_date < cast(p.c as date))
       group by 1),
cu as (select p.ptp_id, date_diff('day', u.since, cast(p.c as date)) tenure_d, u.inc, u.emp, u.iv
       from p join (select crm_customer_id, any_value(customer_since_date) since,
                           any_value(declared_annual_income)::double inc, any_value(employment_status) emp,
                           any_value(income_verified_flag)::int iv from silver.customers group by 1) u using (crm_customer_id)),
xw as (select x.source_system sys, x.source_key k, g.source_key crm from gold.identity_crosswalk x
       join gold.identity_crosswalk g on g.golden_customer_id = x.golden_customer_id and g.source_system = 'crm'
        and g.valid_to is null where x.valid_to is null and x.source_system in ('bureau', 'deposit')),
bu as (select p.ptp_id, arg_max(b.risk_score, b.pull_date) rs, arg_max(b.revolving_utilisation, b.pull_date) ru,
              arg_max(b.delinquent_trades_count, b.pull_date) dt, arg_max(b.inquiries_hard_6m, b.pull_date) inq,
              arg_max(b.risk_score, b.pull_date) - arg_min(b.risk_score, b.pull_date) rsd
       from p join xw on xw.sys = 'bureau' and xw.crm = p.crm_customer_id
       join silver.bureau_history b on b.bank_subject_ref = xw.k
        and b.pull_date < cast(p.c as date) and b.pull_date >= cast(p.c as date) - 100 group by 1),
tx as (select p.ptp_id,
              sum(t.amount) filter (where t.direction = 'credit') in30, sum(t.amount) filter (where t.direction = 'debit') out30,
              count(*) filter (where t.category = 'high_cost_lender') hcl30,
              sum(t.amount) filter (where t.txn_type = 'payroll') pay30, sum(t.amount) filter (where t.category = 'benefits') ben30,
              min(t.balance_after) minbal30, arg_max(t.balance_after, t.txn_ts) lastbal,
              count(*) filter (where t.category = 'debt_payment') debt30,
              date_diff('day', max(t.txn_ts) filter (where t.txn_type = 'payroll'), any_value(p.c)) since_pay
       from p join silver.deposit_accounts d on true
       join xw on xw.sys = 'deposit' and xw.k = d.src_customer_ref and xw.crm = p.crm_customer_id
       join silver.transactions t on t.account_id = d.deposit_account_id
        and t.txn_ts < p.c and t.txn_ts >= p.c - interval 45 day group by 1)
select p.ptp_id, p.ptp_channel, p.ptp_type, p.product, p.payment_method_promised, p.seq, p.pbc, ln(1 + p.overdue) lod,
       p.rem::int rem, p.due - p.sid sid_gap, ch.n30, ch.rpc30, ch.inb30, ch.n7, sn.bal / nullif(sn.lim, 0) util,
       sn.pay / nullif(sn.mind, 0) paycov, sn.sal, sn.ovl, cu.tenure_d, cu.inc, cu.emp, cu.iv,
       bu.rs, bu.ru, bu.dt, bu.inq, bu.rsd, tx.in30, tx.out30, tx.hcl30, tx.pay30, tx.ben30, tx.minbal30, tx.lastbal,
       tx.debt30, tx.since_pay, tx.in30 - tx.out30 net30, p.overdue / nullif(tx.in30, 0) od_in
from p left join ch using (ptp_id) left join sn using (ptp_id) left join cu using (ptp_id) left join bu using (ptp_id)
left join tx using (ptp_id)"""
SQL_HISTORY = """
with p as (select ptp_id, account_id, crm_customer_id, ptp_created_ts c, cast(ptp_created_ts as date) cd,
                  cast(ptp_created_ts as date) - 100 cd100
           from silver.promises_to_pay where ptp_status in ('kept','partially_kept','broken')),
cs as (select p.ptp_id, count(*) c_n,
          avg(s.min_paid_flag::int) filter (where s.due_date >= p.cd - 190) c_min6, avg(s.min_paid_flag::int) c_min12,
          avg(s.paid_in_full_flag::int) filter (where s.due_date >= p.cd - 190) c_full6,
          avg(least(coalesce(s.amount_paid_by_due, 0) / nullif(s.minimum_due, 0), 3)) filter (where s.due_date >= p.cd - 190) c_paycov6,
          max(s.cycles_delinquent_at_statement) c_maxdel12,
          arg_max(s.closing_balance / nullif(s.credit_limit_at_statement, 0), s.statement_date) c_util,
          arg_max(s.closing_balance, s.statement_date) / nullif(arg_min(s.closing_balance, s.statement_date), 0) c_baltrend,
          sum(s.cash_advances_amount) filter (where s.due_date >= p.cd - 190) c_cash6,
          sum(s.purchases_amount) filter (where s.due_date >= p.cd - 100) c_purch3,
          avg(s.days_late) filter (where s.due_date < p.cd - 35) c_late12
       from p join silver.card_statements s on s.card_account_id = p.account_id
        and s.due_date < p.cd and s.due_date >= p.cd - 370 group by 1),
li as (select p.ptp_id, count(*) l_n,
          avg((i.paid_date is not null and i.paid_date <= i.due_date)::int) l_ontime12,
          avg((i.paid_date is null or i.paid_date >= p.cd)::int) l_unpaid12,
          count(*) filter (where i.pad_result = 'nsf' and i.pad_attempt_date < p.cd and i.pad_attempt_date >= p.cd - 92) l_nsf3,
          count(*) filter (where i.pad_result = 'nsf' and i.pad_attempt_date < p.cd) l_nsf12,
          avg(case when i.paid_date < p.cd then date_diff('day', i.due_date, i.paid_date) end) l_late,
          max(i.restructured_flag::int) l_restr, max(i.deferred_flag::int) l_defer
       from p join silver.loan_instalments i on i.loan_id = p.account_id
        and i.due_date < p.cd and i.due_date >= p.cd - 370 group by 1),
sn as (select p.ptp_id, regr_slope(s.dpd, epoch(s.month_end_date) / 86400 / 30) s_dpd_slope,
          avg(least(s.payment_made / nullif(s.minimum_due, 0), 3)) s_paycov6,
          regr_slope(s.balance, epoch(s.month_end_date) / 86400 / 30) s_bal_slope,
          count(distinct s.account_id) s_accts, sum((s.dpd > 0)::int) s_delinq_months
       from p join silver.account_monthly_snapshot s on s.crm_customer_id = p.crm_customer_id
        and s.month_end_date < p.cd and s.month_end_date >= p.cd - 190 group by 1),
pp as (select a.ptp_id, count(*) p_all, count(*) filter (where b.ptp_status = 'cancelled') p_cancel,
          count(*) filter (where b.ptp_status = 'partially_kept') p_part,
          date_diff('day', max(b.ptp_created_ts), any_value(a.c)) p_since_last
       from p a join silver.promises_to_pay b on b.crm_customer_id = a.crm_customer_id and b.ptp_created_ts < a.c
        and (b.status_ts < a.c or b.ptp_status = 'open') group by 1),
sal as (select p.ptp_id, h.first_credit_date, h.last_credit_date, h.credit_count, h.credit_amount_total::double amt,
               h.gap_flag, h.employer_flag, p.cd, p.cd100
        from p join silver.salary_credit_history h on h.crm_customer_id = p.crm_customer_id
         and h.last_credit_date < p.cd and h.last_credit_date >= p.cd - 200),
py as (select ptp_id, date_diff('day', max(last_credit_date), any_value(cd)) pay_days_since,
          date_diff('day', max(last_credit_date), any_value(cd))
            - avg(date_diff('day', first_credit_date, last_credit_date) / greatest(credit_count - 1, 1)) pay_delay,
          sum(gap_flag::int) filter (where last_credit_date >= cd100) pay_gaps3,
          arg_max(amt, last_credit_date) / nullif(avg(amt), 0) pay_change, avg(credit_count) pay_count,
          max((employer_flag = 'Y')::int) pay_employer
       from sal group by 1)
select p.ptp_id, cs.* exclude (ptp_id), li.* exclude (ptp_id), sn.* exclude (ptp_id), pp.* exclude (ptp_id),
       py.* exclude (ptp_id), extract(month from p.c) mon, extract(dow from p.c) wd
from p left join cs using (ptp_id) left join li using (ptp_id) left join sn using (ptp_id) left join pp using (ptp_id)
left join py using (ptp_id)"""
CATEGORIES = ("ptp_channel", "ptp_type", "product", "payment_method_promised", "emp")
# the kept rate fell from ~63% to ~35% in mid-2026, so recent promises count more: weight 0.5 ** (age / HALF_LIFE_DAYS).
# The half-life and tree settings were chosen on the 45 days before the cut (validation), then the test was scored once.
HALF_LIFE_DAYS = 30
GBM_WIDE = dict(n_estimators=1500, num_leaves=31, min_child_samples=300, learning_rate=0.01, subsample=0.8,
                subsample_freq=1, colsample_bytree=0.8, verbose=-1, deterministic=True, force_row_wise=True)


def wide_split(con: duckdb.DuckDBPyConnection, rows: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, list[str], pd.Timestamp]:
    """§8's data: every resolved promise with the wide inputs (r), the §6 promises the bank scored before their outcome
    with its score (h), the input names, and the cut (the median promise date of h; test = h from the cut)."""
    w = con.execute(SQL_WIDE).df().merge(con.execute(SQL_HISTORY).df(), on="ptp_id")
    r = rows.drop(columns=["amount_ratio"], errors="ignore").merge(w, on="ptp_id").sort_values(["created", "ptp_id"])
    r = r.reset_index(drop=True)  # a fixed row order: LightGBM's bagging depends on it
    for c in CATEGORIES:
        r[c] = r[c].astype("category")
    feats = [*pm.FEATURES, *(c for c in w.columns if c != "ptp_id")]
    bank = pd.read_csv(
        REPO / "data" / "raw" / "model_scores.csv", usecols=["model_name", "ptp_id", "score", "score_date"], low_memory=False
    )
    bank = bank[bank.model_name == "ptp_break"].drop_duplicates("ptp_id", keep="last")
    dates = con.execute("select ptp_id, cast(status_ts as date) od, ptp_due_date due from silver.promises_to_pay").df()
    h = r.merge(bank, on="ptp_id").merge(dates, on="ptp_id")
    h = h[pd.to_datetime(h.score_date) < pd.to_datetime(h.od)].reset_index(drop=True)  # as §6
    return r, h, feats, h.created.quantile(0.5)


def standalone(con: duckdb.DuckDBPyConnection, rows: pd.DataFrame) -> str:
    """A standalone model with the kinds of inputs the bank's score names in its reason codes (balances, bureau,
    contacts, cash flow), every one dated before the promise, against the bank's score on the §6 promises."""
    from scipy.stats import rankdata
    from sklearn.ensemble import RandomForestClassifier

    r, h, feats, cut = wide_split(con, rows)
    test = h[h.created >= cut].reset_index(drop=True)
    fit = (r.created < cut).to_numpy()
    wt = 0.5 ** ((cut - r.created).dt.days.to_numpy() / HALF_LIFE_DAYS)
    gbm = LGBMClassifier(**GBM_WIDE).fit(r.loc[fit, feats], r.kept[fit], sample_weight=wt[fit])

    def codes(df: pd.DataFrame) -> pd.DataFrame:
        x = df[feats].copy()
        for c in CATEGORIES:
            x[c] = x[c].cat.codes
        return x.astype(float).fillna(-999)

    forest = RandomForestClassifier(500, min_samples_leaf=50, max_features=0.3, n_jobs=-1, random_state=0).fit(
        codes(r[fit]), r.kept[fit], sample_weight=wt[fit]
    )
    p_gbm = gbm.predict_proba(test[feats])[:, 1]
    p_cons = (rankdata(p_gbm) + rankdata(forest.predict_proba(codes(test))[:, 1])) / 2
    preds = {"Bank's ptp_break v2.1": -test.score.to_numpy(), "Kept, 6 features (as shipped)": None,
             "Kept, wide: LightGBM": p_gbm, "Kept, wide: LightGBM + random forest, averaged ranks": p_cons}
    six = LGBMClassifier(n_estimators=200, num_leaves=15, min_child_samples=200, learning_rate=0.05, verbose=-1,
                         deterministic=True, force_row_wise=True).fit(
        h.loc[h.created < cut, list(pm.FEATURES)].astype(float), h.kept[h.created < cut])
    preds["Kept, 6 features (as shipped)"] = six.predict_proba(test[list(pm.FEATURES)].astype(float))[:, 1]
    # nothing fitted on the test: an equal-weight average of the two rankings
    preds["Kept's wide model and the bank's score, averaged ranks"] = rankdata(p_cons) + rankdata(-test.score.to_numpy())
    y = test.kept.to_numpy()
    before_due = (pd.to_datetime(test.score_date) < pd.to_datetime(test.due)).to_numpy()
    rng = np.random.default_rng(0)
    out = [
        f"| Model | AUC, all {len(test):,} | Against the bank's [95% CI] | AUC, the {before_due.sum():,} the bank scored before the due date | Against the bank's [95% CI] |",
        "|---|---:|---:|---:|---:|",
    ]
    bank_p = preds["Bank's ptp_break v2.1"]
    for name, p in preds.items():
        cells = []
        for m in (np.ones(len(y), bool), before_due):
            yy, pp, bb = y[m], p[m], bank_p[m]
            cells.append(f"{roc_auc_score(yy, pp):.3f}")
            if p is bank_p:
                cells.append("—")
                continue
            draws = (rng.integers(0, len(yy), len(yy)) for _ in range(BOOT))
            gap = [roc_auc_score(yy[i], pp[i]) - roc_auc_score(yy[i], bb[i]) for i in draws]
            d = roc_auc_score(yy, pp) - roc_auc_score(yy, bb)
            EV[f"auc|{name}|{'all' if m.all() else 'before_due'}"] = (
                float(roc_auc_score(yy, pp)), 100 * d, 100 * float(np.percentile(gap, 2.5)), 100 * float(np.percentile(gap, 97.5))
            )
            cells.append(f"{100 * d:+.1f} [{100 * np.percentile(gap, 2.5):+.1f}, {100 * np.percentile(gap, 97.5):+.1f}]")
        out.append(f"| {name} | " + " | ".join(cells) + " |")
    return "\n".join(out) + (
        f"\n\n{len(feats)} inputs, trained on the {fit.sum():,} promises made before the cut, recent ones weighted more "
        f"(half-life {HALF_LIFE_DAYS} days)."
    )


def promise_decision(con: duckdb.DuckDBPyConnection, rows: pd.DataFrame) -> str:
    """Decision B9 (docs/reports/decisions.md): which promise model ships. §8's split and test promises; adds logistic
    regression on the 6 features, the 6-feature LightGBM raw / Platt / isotonic, and the wide LightGBM raw / isotonic.
    Calibrators are fitted on the bank-scored promises of the last 20% of the training period (the base model is
    refitted on the 80% before it, so no calibrator sees its own base model's training data or the test). The raw rows are
    shown on both bases. Writes data/exports/reports/decision_B9.json."""
    import inspect
    import json

    from sklearn.impute import SimpleImputer
    from sklearn.isotonic import IsotonicRegression  # type: ignore[import-untyped]
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import brier_score_loss
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    r, h, feats, cut = wide_split(con, rows)
    six_f = list(pm.FEATURES)
    test = h[h.created >= cut].reset_index(drop=True)
    y = test.kept.to_numpy()
    cut2 = h.created[h.created < cut].quantile(0.8)  # calibration window: [cut2, cut)
    wt = 0.5 ** ((cut - r.created).dt.days.to_numpy() / HALF_LIFE_DAYS)
    cal = h[(h.created >= cut2) & (h.created < cut)].reset_index(drop=True)
    six_kw = dict(n_estimators=200, num_leaves=15, min_child_samples=200, learning_rate=0.05, verbose=-1, deterministic=True, force_row_wise=True)

    def six_gbm(df: pd.DataFrame) -> LGBMClassifier:
        return LGBMClassifier(**six_kw, n_jobs=4).fit(df[six_f].astype(float), df.kept)

    def wide_gbm(m: np.ndarray) -> LGBMClassifier:
        return LGBMClassifier(**GBM_WIDE, n_jobs=4).fit(r.loc[m, feats], r.kept[m], sample_weight=wt[m])

    def sx(df: pd.DataFrame) -> pd.DataFrame:
        return df[six_f].astype(float)

    base = {"six": six_gbm(h[h.created < cut2]), "wide": wide_gbm((r.created < cut2).to_numpy())}
    full = {"six": six_gbm(h[h.created < cut]), "wide": wide_gbm((r.created < cut).to_numpy())}
    lr = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), LogisticRegression(max_iter=1000)).fit(sx(h[h.created < cut]), h.kept[h.created < cut])
    f = {"six": lambda m, d: m.predict_proba(sx(d))[:, 1], "wide": lambda m, d: m.predict_proba(d[feats])[:, 1]}

    def logit(p: np.ndarray) -> np.ndarray:
        p = np.clip(p, 1e-6, 1 - 1e-6)
        return np.log(p / (1 - p))

    def platt(kind: str) -> np.ndarray:
        m = LogisticRegression(C=1e6, max_iter=1000).fit(logit(f[kind](base[kind], cal))[:, None], cal.kept)
        return m.predict_proba(logit(f[kind](base[kind], test))[:, None])[:, 1]

    def iso(kind: str) -> np.ndarray:
        m = IsotonicRegression(out_of_bounds="clip").fit(f[kind](base[kind], cal), cal.kept)
        return m.predict(f[kind](base[kind], test))

    last = "first 80%, calibrated on the last 20%"
    preds = {  # name -> (probabilities, fitted on)
        "Logistic regression, 6 features": (lr.predict_proba(sx(test))[:, 1], "full training period"),
        "6-feature LightGBM, no calibration (as §8)": (f["six"](full["six"], test), "full training period"),
        "6-feature LightGBM, no calibration": (f["six"](base["six"], test), "first 80%"),
        "6-feature LightGBM, Platt": (platt("six"), last),
        "6-feature LightGBM, isotonic": (iso("six"), last),
        "Wide LightGBM, no calibration (as §8)": (f["wide"](full["wide"], test), "full training period"),
        "Wide LightGBM, no calibration": (f["wide"](base["wide"], test), "first 80%"),
        "Wide LightGBM, isotonic": (iso("wide"), last),
    }
    rng = np.random.default_rng(0)
    draws = [rng.integers(0, len(y), len(y)) for _ in range(BOOT)]
    res = {"test_promises": len(y), "kept_rate_test": float(y.mean()), "calibration_promises": len(cal), "calibration_window": [str(cut2), str(cut)],
           "cut": str(cut), "bank_auc": float(roc_auc_score(y, -test.score.to_numpy())), "models": {}}
    out = [f"| Model | Fitted on | AUC [95% CI] | Brier | Calibration gap, pts | Mean predicted (kept {100 * y.mean():.0f}%) |", "|---|---|---:|---:|---:|---:|"]
    for name, (p, how) in preds.items():
        auc = roc_auc_score(y, p)
        ci = np.percentile([roc_auc_score(y[i], p[i]) for i in draws], [2.5, 97.5])
        b = np.clip((p * 10).astype(int), 0, 9)
        gap = sum(abs(p[b == k].mean() - y[b == k].mean()) * (b == k).mean() for k in range(10) if (b == k).any())
        res["models"][name] = dict(fitted=how, auc=float(auc), auc_ci=[float(c) for c in ci], brier=float(brier_score_loss(y, p)),
                                   calibration_gap_pts=float(100 * gap), mean_predicted=float(p.mean()))
        out.append(f"| {name} | {how} | {auc:.3f} [{ci[0]:.3f}, {ci[1]:.3f}] | {brier_score_loss(y, p):.3f} | {100 * gap:.1f} | {p.mean():.2f} |")

    def sql_lines(s: str) -> int:
        return len([ln for ln in s.splitlines() if ln.strip()])

    res["serving"] = {"six_features": len(six_f), "six_sql_lines": sql_lines(inspect.getsource(pm.load)), "wide_features": len(feats),
                      "wide_sql_lines": sql_lines(SQL_WIDE) + sql_lines(SQL_HISTORY)}
    (REPO / "data" / "exports" / "reports" / "decision_B9.json").write_text(json.dumps(res, indent=1))
    return "\n".join(out)


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
    ap.add_argument("--only-b9", action="store_true", help="decision B9: only the §8 promise-model variants, no report written")
    a = ap.parse_args()
    con = duckdb.connect(a.warehouse, read_only=True)
    # one thread: parallel scans break arg_max ties (bureau pulls on one date) and sum order differently each run
    con.execute(f"set memory_limit = '{'3GB' if a.only_b9 else '8GB'}'; set threads = 1")
    rows = pm.load(con).merge(  # the leaky ratio the shipped model dropped, for the audit only
        con.execute(
            "select ptp_id, ptp_to_overdue_ratio::double as amount_ratio from silver.promises_to_pay"
        ).df(),
        on="ptp_id",
    )
    if a.only_b9:
        print(promise_decision(con, rows))
        return
    cell_md = cells(con)
    pay_md, pay_sum = payday(con, rows)
    day_md, design_md = payday_designs(con)
    abl_md, h2h_md, where_md = models(con, rows)
    wide_md = standalone(con, rows)
    wide_md += "\n\nSame promises, the shipped model's family and the wide one with other models and calibrations (decision B9; the calibrated rows refit the base on the first 80% of the training period and calibrate on the last 20%, never on the test):\n\n" + promise_decision(con, rows)
    uplift_md = cell_uplift(con)
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

## 2a. Is it the payday? Three checks

Without randomised due dates, the question is whether something else that comes with payday-dated promises explains
§2. These checks use every resolved promise with a recorded payday on each side of its due date, not only the
randomised cases, and compare within days-past-due bands.

{day_md:s}

{design_md:s}

- **Sharp comparison.** Promises due on payday are kept far more often than those due a day or three either side, and
  the days on either side look alike. A difference in the customers would not switch on and off within a day.
- **The same customer.** Comparing each customer only with themselves removes everything fixed about the customer
  (income, attitude, history): the effect shrinks but stays above zero.
- **Fake paydays.** Moving every payday by 3 to 10 days, with promises near a real payday removed, the "effect" at the
  fake payday disappears: every interval includes zero.

The peak is the payday itself: a promise due the day after payday does no better than one due the day before. The
bank's deposit data records only the first and last credit of each month, so for customers paid weekly or every two
weeks some paydays are missing; promises due on those show up 7 days from a recorded one, where kept rates spike too.

## 3. Promise model: leakage audit

{abl_md:s}

One feature, `amount_ratio` (promised amount ÷ overdue amount), carries almost all of the 0.92. It is computed correctly
at promise time, but in this data a full-balance promise is all but certain to be kept:

{ratio_table(con):s}

That is too clean to be real behaviour, so we treat it as an artefact of how the data was generated and **headline the
leak-free model**. Kept's promise model drops this feature (phase 2).

## 4. Kept's contact policy against what the bank did, off-policy

{off_policy(con):s}

Read the first row. On the clean outcome, **Kept's choice of action is no better than what the bank did**: the interval
on the difference includes zero. The bigger gain on the old label (rows 2 and 3) comes from SMS and email payments that
exist only as flags on the contact row and leave no trace in the account records (`uplift_improvement.md`), so it is not
evidence of a better choice of whom to contact. Which action to take wasn't randomised (the bank chose it), so every
number here is an estimate: outcome models per action and a model of how the bank chose, cross-fitted by case, on the
decisions where the bank had a real chance (5% to 95%) of choosing Kept's action; the bank's value is simply what
happened on those same decisions. The earlier version of this section compared Kept's choice with the bank's
recommendation field (+61 per 1,000, 38.6-42.0% against 32.4-32.5%); that field is the last recommendation shown as of
the snapshot, so it encodes how each case ended, and the comparison is withdrawn. **What Kept can claim measured is
timing** (§2, and the best hour to call, `docs/reports/best_hour.md`), not a better choice of whom to contact; a randomised
pilot cell is the way to find out whether targeting adds anything.

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

## 8. A standalone model with the bank's kinds of inputs

The bank's reason codes name what its score uses: returned payments, utilisation, bureau score changes, contact history,
payroll delay, tenure. Kept has the same kinds of data. This model takes the inputs below, each dated before the
promise: the promise's own details (channel, product, type); the customer's repayment record (card statements over the
last 12 cycles, loan instalments paid late, returned pre-authorised debits); month-end balances and their 6-month
trend; the customer record; the latest bureau pull; contacts in the 30 days before; the deposit account's cash flow;
and payroll (days since the last pay against the usual interval, gaps, pay against its average). The kept rate fell
from about 63% to 35% in mid-2026, so recent promises are weighted more. The weighting and the tree settings were chosen
on the 45 days before the cut; the test promises were scored once.

{wide_md:s}

**Matched, not beaten.** On its own, the wide model ranks promises as well as the bank's score: the gap is a fraction
of a point and its interval includes zero, both on all promises and on those the bank scored before the due date.
That is up from 7.8 points behind for the shipped six-feature model. **Together, the two are far better than either:**
an equal-weight average of the two rankings, with nothing fitted on the test, gains about 6 AUC points over the bank's
score alone, so most of what Kept's model knows, the bank's doesn't. We tried and dropped: random forest, extra trees
and logistic regression alone, a spline GLM stacked with the trees, one model per product or channel, the agent's past
kept rate, call audio measures and the note text (none added beyond the noise). Features dated after the promise score
0.79, but only by seeing contacts after a missed due date, so they are excluded.

## 9. Uplift where the bank randomised

The live uplift model learns from randomly assigned cases, but within them the action each day was the strategy's
choice, not random. The one thing the bank did randomise is the cell: a case was either worked by a strategy or held
out. This model uses only that: one LightGBM for worked cases and one for held-out cases, on what is known when the
case opens, with overdue dollars cured within 30 days as the outcome. Because the arms were randomised, the difference
inside any group of cases is an unbiased estimate of what working them added.

{uplift_md:s}

The estimates rise as the model's top cases are taken first, which is what a working uplift ranking looks like, but
**every interval includes zero**: the held-out arm in this window is small and was mostly contacted anyway (§1). So on
the bank's randomisation alone, targeting by uplift is promising and unproven. That matches §1: contact intensity barely
changes outcomes, which is why Kept's main lever is the due date (§2), and why the uplift model only replaces the
bank's strategy behind a gate (`docs/reports/tuning.md`).
""")
    import json

    (REPO / "data" / "exports" / "reports" / "evidence.json").write_text(json.dumps(EV, indent=1, default=float))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
