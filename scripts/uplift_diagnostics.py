# ruff: noqa: E501, B023  (report prose; loop variables in bootstrap lambdas are used before the next iteration)
"""Step 0: is there an effect of contact to find, and does the live model's uplift ranking hold up?

    uv run python scripts/uplift_diagnostics.py [--warehouse data/warehouse/kept.duckdb]

Reads the training rows (features_train.training_rows joined to case_features, as `kept train`), adds point-in-time
context (pending promise, contacts in the last 7/30 days, payments in the last 7 days; `CONTEXT_SQL`), and writes
data/exports/reports/uplift_diagnostics.json (tables are printed). Four questions:
  1. overlap: how well do the 17 inputs (plus context) predict which action the bank chose, per arm against WAIT?
  2. average effect: doubly robust (cross-fitted, case-grouped) effect per arm vs WAIT with case-bootstrap CIs, next to the naive difference;
  3. heterogeneity: best-linear-predictor test and DR Qini of an out-of-fold DR-learner, case-bootstrap CIs;
  4. stability: the live T-learner's gate Qini over rolling windows, 3 seeds, case-bootstrap noise.
"""

from __future__ import annotations

import argparse
import json
import pickle
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from sklearn.metrics import roc_auc_score

from kept.nba.causal import blp, case_bootstrap, crossfit, dr_qini, folds, gate_qini
from kept.nba.train import ACTIONS, CONTEXT_COLS, base_inputs, load_rows
from kept.nba.uplift import TLearnerUplift, _frame

REPO = Path(__file__).resolve().parents[1]
COLS = base_inputs()
ARMS = ("call", "sms_payment_link", "email")
CUT = datetime(2026, 8, 15)
# context at the decision, same sources as the label (contact_history, promises_to_pay); never the decision's own contact
CONTEXT_SQL = """
select t.decision_id,
  cast(exists (select 1 from silver.promises_to_pay p where p.crm_customer_id = t.crm_customer_id and p.ptp_created_ts < t.decision_at
        and (p.status_ts is null or p.status_ts >= t.decision_at)) as int) as pending_ptp,
  (select min(p.ptp_due_date) - cast(t.decision_at as date) from silver.promises_to_pay p where p.crm_customer_id = t.crm_customer_id
        and p.ptp_created_ts < t.decision_at and (p.status_ts is null or p.status_ts >= t.decision_at)) as ptp_due_in_days,
  (select count(*) from silver.contact_history h where h.case_id = t.case_id and h.direction = 'outbound'
        and h.contact_ts_utc < t.decision_at and h.contact_ts_utc >= t.decision_at - interval 7 day) as n_out_7d,
  (select count(*) from silver.contact_history h where h.case_id = t.case_id and h.direction = 'outbound'
        and h.contact_ts_utc < t.decision_at and h.contact_ts_utc >= t.decision_at - interval 30 day) as n_out_30d,
  (select count(*) from silver.contact_history h where h.case_id = t.case_id and h.direction = 'outbound' and h.rpc_flag
        and h.contact_ts_utc < t.decision_at and h.contact_ts_utc >= t.decision_at - interval 30 day) as n_rpc_30d,
  (select epoch(t.decision_at - max(h.contact_ts_utc)) / 86400.0 from silver.contact_history h where h.case_id = t.case_id
        and h.direction = 'outbound' and h.contact_ts_utc < t.decision_at) as days_since_contact,
  cast(exists (select 1 from silver.contact_history h where h.crm_customer_id = t.crm_customer_id
        and (h.payment_taken_flag or h.link_payment_flag or h.app_payment_after_contact_flag)
        and h.contact_ts_utc < t.decision_at and h.contact_ts_utc >= t.decision_at - interval 7 day)
      or exists (select 1 from silver.promises_to_pay p where p.crm_customer_id = t.crm_customer_id and p.ptp_status in ('kept', 'partially_kept')
        and cast(p.paid_date as timestamp) + interval 12 hour < t.decision_at
        and cast(p.paid_date as timestamp) + interval 12 hour >= t.decision_at - interval 7 day) as int) as paid_prev7
from features_train.training_rows t where t.paid_14d_known
"""
COVERED_SQL = """
select distinct case_id from features_train.training_rows where case_id in (select case_id from silver.collections_cases)
 and case_id in (select a.case_id from (select case_id, unnest(case when account_ids like '[%' then from_json(account_ids, '["VARCHAR"]') else [account_ids] end) as account_id
        from silver.collections_cases) a where a.account_id like 'L-%' or a.account_id in (select distinct target_account_id from silver.transactions where target_account_id is not null))
"""


def load(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    rows = load_rows(conn)
    ctx = conn.sql(CONTEXT_SQL).df()
    covered = set(conn.sql(COVERED_SQL).df().case_id)
    rows = rows.merge(ctx, on="decision_id", how="left")
    rows["covered"] = rows.case_id.isin(covered)
    rows["ptp_due_in_days"] = rows.ptp_due_in_days.astype(float)
    return rows


def overlap(rows: pd.DataFrame, cols: list[str]) -> list[dict[str, Any]]:
    """Out-of-fold propensity per arm against WAIT: AUC, spread, and how many rows fall outside the clip."""
    from lightgbm import LGBMClassifier

    from kept.nba.causal import CLIP, NUIS

    out = []
    for arm in ARMS:
        d = rows[rows.action.isin([arm, "wait"])]
        fd, t = folds(d.case_id, 5), (d.action == arm).to_numpy()
        e = np.zeros(len(d))
        X = _frame(d[cols])
        for i in range(5):
            e[fd == i] = LGBMClassifier(**NUIS).fit(X[fd != i], t[fd != i]).predict_proba(X[fd == i])[:, 1]
        out.append(
            {"arm": arm, "n_arm": int(t.sum()), "n_wait": int((~t).sum()), "auc": float(roc_auc_score(t, e)),
             "e_q05_q50_q95_arm": np.quantile(e[t], [0.05, 0.5, 0.95]).round(3).tolist(),
             "e_q05_q50_q95_wait": np.quantile(e[~t], [0.05, 0.5, 0.95]).round(3).tolist(),
             "share_outside_clip": float(((e < CLIP[0]) | (e > CLIP[1])).mean())}
        )  # fmt: skip
    return out


def effects(rows: pd.DataFrame, cols: list[str], label: str) -> list[dict[str, Any]]:
    """DR average effect and heterogeneity per arm, on all of `rows` (cross-fitted: nuisance and CATE models never see the row's case)."""
    res = []
    for arm in ARMS:
        ps = crossfit(rows, cols, arm)
        d = rows.loc[ps.index]
        phi, t, y = ps.phi.to_numpy(), ps.t.to_numpy(), ps.y.to_numpy()
        naive = y[t == 1].mean() - y[t == 0].mean()
        ate = case_bootstrap(d.case_id, lambda w: (w * phi).sum() / w.sum(), reps=300)
        # heterogeneity: second stage fitted out of fold on the other folds' pseudo-outcomes
        f = folds(d.case_id, 5, seed=1)
        X, tau = _frame(d[cols]), np.zeros(len(d))
        for i in range(5):
            tau[f == i] = (
                LGBMRegressor(
                    n_estimators=200,
                    num_leaves=7,
                    min_child_samples=1000,
                    learning_rate=0.03,
                    reg_lambda=20.0,
                    colsample_bytree=0.8,
                    verbose=-1,
                )
                .fit(X[f != i], phi[f != i])
                .predict(X[f == i])
            )
        b = blp(phi, tau, d.case_id)
        q = dr_qini(tau, phi)
        qs = case_bootstrap(d.case_id, lambda w: dr_qini(tau, phi, w), reps=200)
        rng = np.random.default_rng(0)
        null = np.std([dr_qini(rng.random(len(phi)), phi) for _ in range(100)])
        res.append(
            {"sample": label, "arm": arm, "rows": len(d), "naive_diff": float(naive), "dr_ate": float(phi.mean()),
             "dr_ate_ci": np.quantile(ate, [0.025, 0.975]).round(4).tolist(), "blp": b,
             "oof_dr_qini": q, "oof_dr_qini_ci": np.quantile(qs, [0.025, 0.975]).round(5).tolist(), "random_noise": float(null)}
        )  # fmt: skip
        print(
            label,
            arm,
            {k: v for k, v in res[-1].items() if k not in ("blp",)},
            {k: round(v, 4) for k, v in b.items()},
            flush=True,
        )
    return res


def stability(rows: pd.DataFrame, seeds: tuple[int, ...] = (0, 1, 2)) -> list[dict[str, Any]]:
    """The live T-learner's gate Qini (call, any contact) on rolling windows, expanding fit window, seeds averaged, case-bootstrap SD."""
    from kept.contracts.enums import Action

    out = []
    wins = [(datetime(2026, 5, 15), datetime(2026, 6, 15)), (datetime(2026, 6, 15), datetime(2026, 7, 15)),
            (datetime(2026, 7, 15), datetime(2026, 8, 15)), (datetime(2026, 8, 15), datetime(2026, 10, 1))]  # fmt: skip
    for s, e in wins:
        fit, ev = rows[rows.decision_at < s], rows[(rows.decision_at >= s) & (rows.decision_at < e)]
        wait = (ev.action == "wait").to_numpy()
        per_seed: dict[str, list[float]] = {"call": [], "any_contact": []}
        last: dict[str, np.ndarray] = {}
        for seed in seeds:
            m = TLearnerUplift(ACTIONS, seed=seed).fit(
                fit[COLS],
                action=fit.action,
                paid_14d=fit.paid_14d,
                is_random_assignment=pd.Series(True, index=fit.index),
            )
            lift = m.uplift(ev[COLS])
            contacts = [a.value for a in m.actions if a is not Action.WAIT]
            for name in per_seed:
                arm = (ev.action == "call").to_numpy() if name == "call" else ~wait
                both = arm | wait
                score = last[name] = (
                    lift["call"] if name == "call" else lift[contacts].max(axis=1)
                ).to_numpy()
                per_seed[name].append(
                    gate_qini(score[both], arm[both].astype(float), ev.paid_14d.to_numpy(float)[both])
                )
        row: dict[str, Any] = {
            "window": f"{s:%d %b} to {min(e, datetime(2026, 9, 14)):%d %b}",
            "rows": len(ev),
            "validation": s == datetime(2026, 7, 15),
        }
        for name, v in per_seed.items():
            arm = (ev.action == "call").to_numpy() if name == "call" else ~wait
            both = arm | wait
            m_score = last[
                name
            ][
                both
            ]  # last seed's scores: the bootstrap SD is for sampling noise, the seed spread is reported separately
            sd = case_bootstrap(
                ev.case_id[both],
                lambda w, m_score=m_score, arm=arm, both=both: gate_qini(
                    m_score, arm[both].astype(float), ev.paid_14d.to_numpy(float)[both], w
                ),
                reps=100,
            ).std()
            row[name] = {
                "mean_over_seeds": float(np.mean(v)),
                "seed_min": float(np.min(v)),
                "seed_max": float(np.max(v)),
                "boot_sd": float(sd),
            }
        out.append(row)
        print(row, flush=True)
    return out


CTX2 = CONTEXT_COLS
# name -> (column, binary, restricted to covered cases, restricted to paid_14d_known rows)
OUTCOMES = {
    "any payment, contact flags included (old label)": ("paid_14d", True, False, True),
    "clean payment (account-sourced, covered cases)": ("paid_clean_14d", True, True, False),
    "clean dollars paid (account-sourced, covered cases)": ("paid_amt_14d", False, True, False),
    "cured within 30 days (all cases)": ("cured_30d", True, False, False),
}
DPD_BANDS = ((-1, 30), (30, 60), (60, 10_000))


def study(df: pd.DataFrame, cols: list[str], arm: str, name: str, label: str) -> dict[str, Any]:
    """One arm against WAIT on one outcome: average effect before and after trimming to propensity in [0.05, 0.95], then (trimmed only)
    the BLP test, out-of-fold DR Qini and, for calls, the effect inside dpd bands."""
    col, binary, cov, known = OUTCOMES[name]
    d = df[df.action.isin([arm, "wait"])]
    d = d[d.covered] if cov else d
    d = d[d.paid_14d_known] if known else d
    d = d.reset_index(drop=True)
    if not binary:  # dollars: the top 0.5% are outliers that decide the average
        d = d.assign(**{col: d[col].clip(upper=d[col].quantile(0.995))})
    ps = crossfit(d, cols, arm, outcome=col, binary=binary)
    keep = ((ps.e >= 0.05) & (ps.e <= 0.95)).to_numpy()
    t_all = ps.t.to_numpy() == 1
    kept = {"arm_kept": float(keep[t_all].mean()), "wait_kept": float(keep[~t_all].mean()), "rows": len(d)}
    prof = (
        d.assign(keep=keep, is_arm=t_all)
        .groupby(["is_arm", "keep"])[["max_dpd", "pending_ptp", "n_out_7d"]]
        .mean()
        .round(2)
    )
    all_ate = case_bootstrap(d.case_id, lambda w: (w * ps.phi.to_numpy()).sum() / w.sum(), reps=200)
    dk = d[keep].reset_index(drop=True)
    ps2 = crossfit(dk, cols, arm, outcome=col, binary=binary, seed=1)
    phi, t = ps2.phi.to_numpy(), ps2.t.to_numpy()
    y = dk[col].to_numpy(float)
    ate = case_bootstrap(dk.case_id, lambda w: (w * phi).sum() / w.sum(), reps=300)
    f = folds(dk.case_id, 5, seed=2)
    X, tau = _frame(dk[cols]), np.zeros(len(dk))
    for i in range(5):
        tau[f == i] = (
            LGBMRegressor(
                n_estimators=200,
                num_leaves=7,
                min_child_samples=1000,
                learning_rate=0.03,
                reg_lambda=20.0,
                colsample_bytree=0.8,
                verbose=-1,
            )
            .fit(X[f != i], phi[f != i])
            .predict(X[f == i])
        )
    q = dr_qini(tau, phi)
    qs = case_bootstrap(dk.case_id, lambda w: dr_qini(tau, phi, w), reps=200)
    rng = np.random.default_rng(0)
    out: dict[str, Any] = {
        "label": label, "outcome": name, "arm": arm, **kept,
        "ate_untrimmed": float(ps.phi.mean()), "ate_untrimmed_ci": np.quantile(all_ate, [0.025, 0.975]).tolist(),
        "naive_trimmed": float(y[t == 1].mean() - y[t == 0].mean()), "ate": float(phi.mean()), "ate_ci": np.quantile(ate, [0.025, 0.975]).tolist(),
        "mean_outcome_wait": float(y[t == 0].mean()), "blp": blp(phi, tau, dk.case_id),
        "oof_dr_qini": q, "oof_dr_qini_ci": np.quantile(qs, [0.025, 0.975]).tolist(),
        "random_noise": float(np.std([dr_qini(rng.random(len(phi)), phi) for _ in range(50)])),
        "kept_profile": prof.reset_index().to_dict("records"),
    }  # fmt: skip
    if arm == "call":
        out["dpd_bands"] = [
            {
                "band": f"{lo + 1}-{hi}",
                "n": int(m.sum()),
                "arm_share": float(t[m].mean()),
                "dr_ate": float(phi[m].mean()),
                "naive": float(y[m & (t == 1)].mean() - y[m & (t == 0)].mean()),
            }
            for lo, hi in DPD_BANDS
            if (m := (dk.max_dpd.to_numpy() > lo) & (dk.max_dpd.to_numpy() <= hi)).sum() > 500
            and 0 < t[m].mean() < 1
        ]
    print(
        label,
        arm,
        name,
        {
            k: (round(v, 4) if isinstance(v, float) else v)
            for k, v in out.items()
            if k
            in (
                "arm_kept",
                "wait_kept",
                "ate_untrimmed",
                "naive_trimmed",
                "ate",
                "ate_ci",
                "oof_dr_qini",
                "oof_dr_qini_ci",
                "random_noise",
            )
        },
        {k: round(v, 3) for k, v in out["blp"].items()},
        flush=True,
    )
    return out


def part2(conn: duckdb.DuckDBPyConnection, out_path: str) -> None:
    res: list[dict[str, Any]] = []
    for label, source in (("case landmarks", "training_weeks"), ("contact attempts", "training_rows")):
        df = load_rows(conn, source=source, extras=True)
        df["last_rpc"] = df.last_rpc.astype(float)
        df["last_ptp_made"] = df.last_ptp_made.astype(float)
        for name in OUTCOMES:
            for arm in ARMS:
                res.append(study(df, COLS + CTX2, arm, name, label))
                Path(out_path).write_text(json.dumps(res, indent=1, default=float))
    # tie-breaker: do link/app payments flagged on the contact move anything recorded for every arm?
    df = load_rows(conn, source="training_rows", extras=True)
    h = conn.sql(
        "select contact_id as decision_id, coalesce(link_payment_flag, false) or coalesce(app_payment_after_contact_flag, false) or coalesce(payment_taken_flag, false) as flagged from silver.contact_history"
    ).df()
    df = df.merge(h, on="decision_id")
    from lightgbm import LGBMClassifier

    tie = []
    for arm in ("email", "sms_payment_link", "call"):
        d = df[(df.action == arm)].reset_index(drop=True)
        f = folds(d.case_id, 5)
        X = _frame(d[COLS + CTX2])
        exp = np.zeros(len(d))
        for i in range(5):
            tr = (f != i) & ~d.flagged.to_numpy()
            exp[f == i] = (
                LGBMClassifier(
                    n_estimators=200, num_leaves=15, min_child_samples=300, learning_rate=0.05, verbose=-1
                )
                .fit(X[tr], d.cured_30d[tr].astype(int))
                .predict_proba(X[f == i])[:, 1]
            )
        fl = d.flagged.to_numpy()
        diff = case_bootstrap(
            d.case_id[fl],
            lambda w, fl=fl, d=d, exp=exp: (w * (d.cured_30d.to_numpy(float)[fl] - exp[fl])).sum() / w.sum(),
            reps=200,
        )
        tie.append(
            {
                "arm": arm,
                "flagged": int(fl.sum()),
                "cured_30d_flagged": float(d.cured_30d[fl].mean()),
                "expected_from_unflagged": float(exp[fl].mean()),
                "diff": float(d.cured_30d[fl].mean() - exp[fl].mean()),
                "diff_ci": np.quantile(diff, [0.025, 0.975]).tolist(),
                "unflagged_rate": float(d.cured_30d[~fl].mean()),
            }
        )
        print("tiebreak", tie[-1], flush=True)
    Path(out_path).write_text(json.dumps({"studies": res, "tiebreak_cure": tie}, indent=1, default=float))


FRAMINGS_JSON = REPO / "data" / "exports" / "reports" / "uplift_framings.json"


def self_cure(conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    """Track 2.1. Who cures with little help? P(cure within ~30 days) from the 17 inputs on the first landmark of each randomly
    assigned case (day 1: nothing about the case's outcome is known), time split on the case open date, then the bank's randomised
    cells: among cases the model calls likely self-curers, do held-out cases (the bank's no_contact_holdout cell) cure like worked ones?"""
    from lightgbm import LGBMClassifier

    from kept.nba.causal import NUIS

    lm = load_rows(conn, source="training_weeks", extras=True)
    meta = conn.sql("""select c.case_id, c.test_cell, c.case_open_date, coalesce(a.attempts, 0) as attempts, coalesce(a.spend, 0) as cost
        from silver.collections_cases c left join (
            select h.case_id, count(*) as attempts, sum(h.contact_cost_cad) as spend
            from silver.contact_history h join silver.collections_cases c2 on c2.case_id = h.case_id
            where h.direction = 'outbound' and h.contact_ts_utc < c2.case_open_date + 34 group by h.case_id) a using (case_id)""").df()
    d = lm.merge(meta, on="case_id")
    d = d[(d.decision_at.dt.normalize() - pd.to_datetime(d.case_open_date)).dt.days == 1]
    d = d[pd.to_datetime(d.case_open_date) < "2026-08-20"].reset_index(drop=True)
    fit, test = (
        d[d.case_open_date < pd.Timestamp("2026-06-01")],
        d[d.case_open_date >= pd.Timestamp("2026-06-01")].copy(),
    )
    X = lambda x: _frame(x[COLS])  # noqa: E731
    from sklearn.isotonic import IsotonicRegression

    # the last fifth of the fit period (by open date) calibrates the model: the case mix drifts, and raw scores were 10-25 points high
    cut = fit.case_open_date.quantile(0.8)
    core, cal = fit[fit.case_open_date <= cut], fit[fit.case_open_date > cut]
    m = LGBMClassifier(**{**NUIS, "n_estimators": 150}).fit(X(core), core.cured_30d.astype(int))
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(
        m.predict_proba(X(cal))[:, 1], cal.cured_30d.astype(float)
    )
    test["p_raw"] = m.predict_proba(X(test))[:, 1]
    test["p"] = iso.predict(test.p_raw)
    y = test.cured_30d.to_numpy(float)
    out: dict[str, Any] = {
        "fit_cases": len(fit),
        "test_cases": len(test),
        "base_rate": float(y.mean()),
        "auc": float(roc_auc_score(y, test.p)),
        "brier_raw": float(np.mean((test.p_raw - y) ** 2)),
        "brier": float(np.mean((test.p - y) ** 2)),
        "brier_constant": float(np.var(y)),
    }
    q = pd.qcut(test.p, 10, labels=False, duplicates="drop")
    out["deciles"] = (
        test.assign(q=q)
        .groupby("q")
        .agg(predicted=("p", "mean"), observed=("cured_30d", "mean"), n=("p", "size"))
        .round(4)
        .reset_index()
        .to_dict("records")
    )
    # more holdout cases: the same model out of fold over every case (cases grouped), instead of the time split
    f5 = folds(d.case_id, 5)
    d = d.assign(p=0.0)
    for i in range(5):
        d.loc[f5 == i, "p"] = (
            LGBMClassifier(**{**NUIS, "n_estimators": 150})
            .fit(X(d[f5 != i]), d.cured_30d[f5 != i].astype(int))
            .predict_proba(X(d[f5 == i]))[:, 1]
        )
    out["auc_oof_all"] = float(roc_auc_score(d.cured_30d, d.p))
    test = d  # the holdout check below uses every case
    held = test.test_cell == "no_contact_holdout"
    out["cells"] = (
        test.groupby("test_cell")
        .agg(
            n=("p", "size"), cure=("cured_30d", "mean"), attempts=("attempts", "mean"), cost=("cost", "mean")
        )
        .round(4)
        .reset_index()
        .to_dict("records")
    )
    rows = []

    def compare(sel: pd.Series, label: Any) -> dict[str, Any]:
        a, b = test[sel & held], test[sel & ~held]
        diff = a.cured_30d.mean() - b.cured_30d.mean()
        se = np.sqrt(
            a.cured_30d.var() / len(a) + b.cured_30d.var() / len(b)
        )  # cases are the units: no clustering to allow for
        return {
            "group": label,
            "n_held": len(a),
            "n_worked": len(b),
            "cure_held": float(a.cured_30d.mean()),
            "cure_worked": float(b.cured_30d.mean()),
            "diff": float(diff),
            "diff_se": float(se),
            "diff_ci": [float(diff - 1.96 * se), float(diff + 1.96 * se)],
            "attempts_held": float(a.attempts.mean()),
            "attempts_worked": float(b.attempts.mean()),
            "cost_worked": float(b.cost.mean()),
            "cost_held": float(a.cost.mean()),
            "predicted": float(test.p[sel].mean()),
        }

    for top in (0.5, 0.3, 0.2, 0.1):
        rows.append({"top_share": top, **compare(test.p >= test.p.quantile(1 - top), f"top {top:.0%}")})
    bottom = compare(test.p < test.p.quantile(0.5), "bottom 50%")
    rows.append({"top_share": None, **bottom})
    top50 = rows[0]
    inter = top50["diff"] - bottom["diff"]
    inter_se = float(np.hypot(top50["diff_se"], bottom["diff_se"]))
    out["interaction_top50_minus_bottom50"] = {
        "diff_in_diff": float(inter),
        "ci": [float(inter - 1.96 * inter_se), float(inter + 1.96 * inter_se)],
    }
    # what skipping or delaying contact is worth: new cases per day (all cases, last year) x share x attempts and cost avoided
    per_day = float(
        conn.sql(
            "select count(*) / 365.0 from silver.collections_cases where case_open_date >= '2025-09-28' and case_open_date < '2026-09-28'"
        ).fetchone()[0]
    )  # type: ignore[index]
    out["cases_per_day"] = per_day
    out["business"] = [
        {
            "share": r["top_share"],
            "delayed_contacts_per_night": per_day
            * r["top_share"]
            * (r["attempts_worked"] - r["attempts_held"]),
            "delayed_cost_per_year": 365 * per_day * r["top_share"] * (r["cost_worked"] - r["cost_held"]),
            "skipped_contacts_per_night_if_none": per_day * r["top_share"] * r["attempts_worked"],
            "skipped_cost_per_year_if_none": 365 * per_day * r["top_share"] * r["cost_worked"],
        }
        for r in rows
        if r["top_share"] in (0.5, 0.3, 0.2)
    ]
    out["holdout_check"] = rows
    print(
        json.dumps({k: v for k, v in out.items() if k not in ("deciles",)}, indent=1, default=float),
        flush=True,
    )
    return out


def best_hour(conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    """Track 2.2. P(right-party contact | hour, weekday, case features) for outbound calls on randomly assigned cases; AUC with and without
    the hour; a within-customer check that the hour effect is not who gets called when; and what booking each call into its best allowed
    hour would add, with the number of calls per hour band kept as it is (capacity) or not."""
    from lightgbm import LGBMClassifier

    from kept.nba.causal import NUIS

    calls = load_rows(conn, extras=True)
    calls = calls[calls.action == "call"]
    h = conn.sql("""select h.contact_id as decision_id, h.contact_hour_local as hour, coalesce(h.rpc_flag, false) as rpc,
          cast(split_part(c.permitted_call_start_local, ':', 1) as int) as win_start, cast(split_part(c.permitted_call_end_local, ':', 1) as int) as win_end
        from silver.contact_history h left join silver.customers c on c.crm_customer_id = h.crm_customer_id""").df()
    d = calls.merge(h, on="decision_id").dropna(subset=["hour"]).reset_index(drop=True)
    d["hour"] = d.hour.astype(int)
    d["win_start"], d["win_end"] = d.win_start.fillna(8).clip(lower=8), d.win_end.fillna(21).clip(upper=21)
    feats = [*COLS, "n_out_7d", "n_rpc_30d", "days_since_contact", "weekday"]

    def frame(x: pd.DataFrame, hr: Any = None) -> pd.DataFrame:
        f = _frame(x[feats])
        if hr is not None:
            f = f.assign(hour=hr)
        return f

    fit, test = d[d.decision_at < CUT].reset_index(drop=True), d[d.decision_at >= CUT].reset_index(drop=True)
    with_h = LGBMClassifier(**NUIS).fit(frame(fit, fit.hour), fit.rpc.astype(int))
    no_h = LGBMClassifier(**NUIS).fit(frame(fit), fit.rpc.astype(int))
    p_act = with_h.predict_proba(frame(test, test.hour))[:, 1]
    out: dict[str, Any] = {
        "calls_fit": len(fit),
        "calls_test": len(test),
        "rpc_rate_test": float(test.rpc.mean()),
        "auc_with_hour": float(roc_auc_score(test.rpc, p_act)),
        "auc_without_hour": float(roc_auc_score(test.rpc, no_h.predict_proba(frame(test))[:, 1])),
    }
    out["by_hour"] = (
        d.groupby("hour")
        .agg(calls=("rpc", "size"), rpc=("rpc", "mean"))
        .round(4)
        .reset_index()
        .to_dict("records")
    )
    # the same call placed at every hour from 8 to 20; allowed = inside the customer's own calling window
    hours = list(range(8, 21))
    P = np.column_stack([with_h.predict_proba(frame(test, np.full(len(test), hh)))[:, 1] for hh in hours])
    allowed = np.column_stack([(test.win_start <= hh) & (hh < test.win_end) for hh in hours])
    allowed[~allowed.any(axis=1)] = True
    Pm = np.where(allowed, P, -1.0)
    best = Pm.max(axis=1)
    eve = np.array(hours) >= 17
    p_eve, p_day = np.where(eve, Pm, -1).max(axis=1), np.where(~eve, Pm, -1).max(axis=1)
    k = int((test.hour >= 17).sum())  # evening slots as booked today
    gain = np.where((p_eve >= 0) & (p_day >= 0), p_eve - p_day, -9)
    top = np.argsort(-gain)[:k]
    cap = np.where(p_day >= 0, p_day, p_eve).copy()
    cap[top] = np.where(gain[top] > -9, p_eve[top], cap[top])
    # capacity-respecting assignment: an evening hour takes no more calls on a weekday than the team handled in it in this window
    caps = test[test.hour >= 17].groupby(["weekday", "hour"]).size().to_dict()
    cap_p = np.where(p_day >= 0, p_day, p_eve).copy()
    left = dict(caps)
    chosen = np.full(len(test), -1)
    for i in np.argsort(-np.where((p_eve >= 0) & (p_day >= 0), p_eve - p_day, -9)):
        if not ((p_eve[i] >= 0) and (p_day[i] >= 0) and p_eve[i] > p_day[i]):
            break
        wd = test.weekday.iloc[i]
        for j in np.argsort(-Pm[i]):
            hh = hours[j]
            if hh >= 17 and Pm[i, j] >= 0 and left.get((wd, hh), 0) > 0:
                left[(wd, hh)] -= 1
                cap_p[i], chosen[i] = Pm[i, j], hh
                break
    moved = chosen >= 0
    assert all(test.win_start.to_numpy()[moved] <= chosen[moved]) and all(
        chosen[moved] < test.win_end.to_numpy()[moved]
    ), "a moved call left the customer's calling window"
    f = lambda w, v: float((w * v).sum() / w.sum())  # noqa: E731
    from kept.nba.causal import case_bootstrap

    base, free, capneutral = (
        case_bootstrap(test.case_id, lambda w, v=v: f(w, v), reps=100) for v in (p_act, best, cap)
    )
    diff_free = case_bootstrap(test.case_id, lambda w: f(w, best) - f(w, p_act), reps=200)
    diff_cap = case_bootstrap(test.case_id, lambda w: f(w, cap) - f(w, p_act), reps=200)
    diff_hourly = case_bootstrap(test.case_id, lambda w: f(w, cap_p) - f(w, p_act), reps=200)
    out["policy"] = {
        "predicted_rpc_as_booked": float(p_act.mean()),
        "predicted_rpc_best_allowed_hour": float(best.mean()),
        "lift_best_hour": float(best.mean() - p_act.mean()),
        "lift_best_hour_ci": np.quantile(diff_free, [0.025, 0.975]).tolist(),
        "predicted_rpc_same_evening_volume": float(cap.mean()),
        "lift_same_evening_volume": float(cap.mean() - p_act.mean()),
        "lift_same_evening_volume_ci": np.quantile(diff_cap, [0.025, 0.975]).tolist(),
        "evening_calls_as_booked": k,
        "predicted_rpc_hourly_capacity": float(cap_p.mean()),
        "lift_hourly_capacity": float(cap_p.mean() - p_act.mean()),
        "lift_hourly_capacity_ci": np.quantile(diff_hourly, [0.025, 0.975]).tolist(),
        "calls_moved_to_evening": int(moved.sum()),
        "calls": len(test),
        "base_sd": float(base.std()),
        "free_sd": float(free.std()),
        "cap_sd": float(capneutral.std()),
    }
    # observed, for comparable calls: deciles of the no-hour model's score, evening against day inside each
    p0 = no_h.predict_proba(frame(test))[:, 1]
    dec = pd.qcut(p0, 10, labels=False, duplicates="drop")
    band = np.where(
        (test.hour >= 17) & (test.hour <= 20), 1, np.where((test.hour >= 8) & (test.hour <= 16), 0, -1)
    )
    rpc = test.rpc.to_numpy(float)

    def strat(w: np.ndarray) -> float:
        tot, acc = 0.0, 0.0
        for q in np.unique(dec):
            m1, m0 = (dec == q) & (band == 1), (dec == q) & (band == 0)
            if w[m1].sum() > 0 and w[m0].sum() > 0:
                n = w[(dec == q)].sum()
                acc += n * ((w[m1] * rpc[m1]).sum() / w[m1].sum() - (w[m0] * rpc[m0]).sum() / w[m0].sum())
                tot += n
        return acc / tot

    sb = case_bootstrap(test.case_id, strat, reps=100)
    out["comparable_calls"] = {
        "evening_minus_day_rpc": strat(np.ones(len(test))),
        "ci": np.quantile(sb, [0.025, 0.975]).tolist(),
        "evening_calls": int((band == 1).sum()),
        "day_calls": int((band == 0).sum()),
    }
    cap_tbl = conn.sql(
        "select time_band, avg(cast(capacity_units as double)) as capacity, avg(cast(used_units as double)) as used from silver.channel_capacity where channel = 'call' group by 1 order by 1"
    ).df()
    out["call_capacity_per_day"] = cap_tbl.round(0).to_dict("records")
    # within-customer: customers called both in the day (8-16h) and evening (17-20h) within the whole period
    e = d.assign(eve=(d.hour >= 17) & (d.hour <= 20), day=(d.hour >= 8) & (d.hour <= 16))
    g = (
        e.groupby("crm_customer_id")
        .apply(
            lambda x: pd.Series({"day": x.rpc[x.day].mean(), "eve": x.rpc[x.eve].mean(), "n": len(x)}),
            include_groups=False,
        )
        .dropna()
    )
    dd = (g.eve - g.day).to_numpy()
    bs = [dd[np.random.default_rng(i).integers(0, len(dd), len(dd))].mean() for i in range(200)]
    out["within_customer"] = {
        "customers": len(dd),
        "evening_minus_day_rpc": float(dd.mean()),
        "ci": np.quantile(bs, [0.025, 0.975]).tolist(),
    }
    print(json.dumps({k: v for k, v in out.items() if k != "by_hour"}, indent=1, default=float), flush=True)
    return out


def part3(conn: duckdb.DuckDBPyConnection) -> None:
    res = {"self_cure": self_cure(conn)}
    FRAMINGS_JSON.write_text(json.dumps(res, indent=1, default=float))
    res["best_hour"] = best_hour(conn)
    FRAMINGS_JSON.write_text(json.dumps(res, indent=1, default=float))


def policy_trees(conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    """Track 2.4 and 2.5. A depth-3 tree on out-of-fold DR scores per arm (clean payment, covered cases, overlap rows): readable segment rules,
    fitted before 15 Aug and valued on the decisions after it by the DR gain of the rows each rule treats, against treating everyone, the live
    model's top rows (same share) and the bank's own recommendation. Then the call split into right-party contact and no contact."""
    from sklearn.tree import DecisionTreeRegressor, export_text

    from kept.nba.causal import CLIP, Nuisance
    from kept.nba.legacy import legacy_to_action

    df = load_rows(conn, extras=True)
    df = df[df.covered].reset_index(drop=True)
    for c in ("last_rpc", "last_ptp_made"):
        df[c] = df[c].astype(float)
    df["bank"] = df.nba_recommendation_last.map(lambda c: (a := legacy_to_action(c)) and a.value)
    fit, test = (
        df[df.decision_at < CUT].reset_index(drop=True),
        df[df.decision_at >= CUT].reset_index(drop=True),
    )
    champ = pickle.loads((REPO / "data" / "exports" / "models" / "uplift.pkl").read_bytes())
    lift = champ.uplift(test[COLS])
    cols = [*COLS, *CONTEXT_COLS]

    def num(
        x: pd.DataFrame,
    ) -> pd.DataFrame:  # a tree takes numbers: category columns as their codes, missing as -1
        f = _frame(x[cols])
        return f.apply(
            lambda c: c.cat.codes if isinstance(c.dtype, pd.CategoricalDtype) else c.astype(float).fillna(-1)
        )

    out: dict[str, Any] = {"policies": []}
    for arm in ("call", "sms_payment_link", "email"):
        ps = crossfit(fit, cols, arm, outcome="paid_clean_14d")
        ok = ((ps.e >= CLIP[0]) & (ps.e <= CLIP[1])).to_numpy()
        d = fit.loc[ps.index][ok]
        X = num(d)
        tree = DecisionTreeRegressor(
            max_depth=3, min_samples_leaf=max(500, len(d) // 100), random_state=0
        ).fit(X, ps.phi.to_numpy()[ok])
        m, o = Nuisance(cols, arm, "paid_clean_14d").fit(fit).pseudo(test)
        te = test[m]
        keep = ((o.e >= CLIP[0]) & (o.e <= CLIP[1])).to_numpy()
        te, phi = te[keep], o.phi.to_numpy()[keep]
        rule = tree.predict(num(te)) > 0
        share = float(rule.mean())
        top = lift[arm].to_numpy()[m][keep]
        champ_rule = top >= np.quantile(top, 1 - share) if share > 0 else np.zeros(len(top), bool)
        rules = {
            "tree (depth 3)": rule,
            "live model, same share": champ_rule,
            "treat everyone": np.ones(len(te), bool),
            "the bank's recommendation": (te.bank == arm).to_numpy(),
        }
        for name, r in rules.items():
            v = case_bootstrap(te.case_id, lambda w, r=r: float((w * phi * r).sum() / w.sum()), reps=200)
            n_r = float(r.mean())
            out["policies"].append(
                {
                    "arm": arm,
                    "rule": name,
                    "share_treated": n_r,
                    "gain_per_1000_decisions": 1000 * float((phi * r).mean()),
                    "gain_ci": (1000 * np.quantile(v, [0.025, 0.975])).tolist(),
                    "extra_payers_per_1000_contacts": 1000 * float((phi * r).sum() / max(r.sum(), 1)),
                }
            )
        out.setdefault("trees", {})[arm] = export_text(tree, feature_names=list(X.columns), decimals=3)
        out["trees_leaf_value_unit"] = (
            "extra probability of a clean payment within 14 days against waiting (DR, overlap rows)"
        )
        print(arm, [p for p in out["policies"] if p["arm"] == arm], out["trees"][arm], flush=True)
    # call = right-party contact x pay: relabel the call arm by whether the call reached the customer
    h = conn.sql(
        "select contact_id as decision_id, coalesce(rpc_flag, false) as rpc from silver.contact_history"
    ).df()
    c = df.merge(h, on="decision_id", how="left")
    c["action"] = np.where(
        (c.action == "call") & c.rpc.fillna(False).astype(bool),
        "call_rpc",
        np.where(c.action == "call", "call_no_rpc", c.action),
    )
    dec = {"p_rpc_given_call": float(c.rpc[c.action.isin(["call_rpc", "call_no_rpc"])].mean())}
    for arm in ("call_rpc", "call_no_rpc"):
        ps = crossfit(c, cols, arm, outcome="paid_clean_14d")
        ok = ((ps.e >= CLIP[0]) & (ps.e <= CLIP[1])).to_numpy()
        v = case_bootstrap(
            c.case_id.loc[ps.index][ok],
            lambda w, ps=ps, ok=ok: float((w * ps.phi.to_numpy()[ok]).sum() / w.sum()),
            reps=200,
        )
        dec[arm] = {
            "dr_effect_vs_wait": float(ps.phi.to_numpy()[ok].mean()),
            "ci": np.quantile(v, [0.025, 0.975]).tolist(),
            "rows_kept_share": float(ok.mean()),
        }
    out["call_decomposition"] = dec
    print(dec, flush=True)
    return out


def seed_table(conn: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    """`kept train`'s own metrics (cutoff 15 Aug, gate Qini) for four model seeds on identical rows: the spread the gate's noise does not show."""
    from kept.nba.train import train

    rows = load_rows(conn)
    out = []
    for seed in range(4):
        _, m = train(rows, cutoff=CUT, seed=seed)
        out.append(
            {
                "seed": seed,
                **{
                    k: m[k]
                    for k in (
                        "qini_call",
                        "qini_any_contact",
                        "noise_call",
                        "noise_any_contact",
                        "qini_legacy_call",
                    )
                },
            }
        )
        print(out[-1], flush=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--warehouse", default=str(REPO / "data" / "warehouse" / "kept.duckdb"))
    ap.add_argument("--out", default=str(REPO / "data" / "exports" / "reports" / "uplift_diagnostics.json"))
    ap.add_argument(
        "--part",
        type=int,
        default=1,
        help="1: Step 0 on the old rows; 2: overlap x clean outcome, both row sets; 3: self-cure and best-hour framings; 4: policy trees and the call split; 5: seed spread of the gate metric",
    )
    args = ap.parse_args()
    conn = duckdb.connect(args.warehouse, read_only=True)
    conn.execute("set memory_limit = '4GB'; set threads = 4")
    if args.part == 3:
        part3(conn)
        return
    if args.part == 5:
        (REPO / "data" / "exports" / "reports" / "uplift_seeds.json").write_text(
            json.dumps(seed_table(conn), indent=1)
        )
        return
    if args.part == 4:
        (REPO / "data" / "exports" / "reports" / "uplift_policy.json").write_text(
            json.dumps(policy_trees(conn), indent=1, default=float)
        )
        return
    if args.part == 2:
        part2(conn, args.out.replace(".json", "_part2.json"))
        return
    rows = load(conn)
    ctx_cols = COLS + CONTEXT_COLS
    res: dict[str, Any] = {}
    prof = rows.groupby("action").agg(
        n=("paid_14d", "size"),
        paid=("paid_14d", "mean"),
        pending_ptp=("pending_ptp", "mean"),
        contacted_prev7=("n_out_7d", lambda s: (s > 0).mean()),
        paid_prev7=("paid_prev7", "mean"),
        covered=("covered", "mean"),
    )
    print(prof.round(3).to_string())
    res["profile"] = prof.round(4).reset_index().to_dict("records")
    res["overlap_17"] = overlap(rows, COLS)
    res["overlap_ctx"] = overlap(rows, ctx_cols)
    print(json.dumps(res["overlap_17"], indent=1), json.dumps(res["overlap_ctx"], indent=1))
    res["effects_all_17"] = effects(rows, COLS, "all known rows, 17 inputs")
    res["effects_all_ctx"] = effects(rows, ctx_cols, "all known rows, 17 inputs + context")
    cov = rows[rows.covered].reset_index(drop=True)
    res["effects_covered_ctx"] = effects(cov, ctx_cols, "covered cases only, 17 inputs + context")
    res["stability"] = stability(rows)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(res, indent=1, default=float))


if __name__ == "__main__":
    main()
