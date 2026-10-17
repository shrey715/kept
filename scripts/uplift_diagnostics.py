# ruff: noqa: E501  (report prose)
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
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from sklearn.metrics import roc_auc_score

from kept.contracts.feature_registry import model_inputs
from kept.nba.causal import blp, case_bootstrap, crossfit, dr_qini, folds, gate_qini
from kept.nba.train import ACTIONS, load_rows
from kept.nba.uplift import TLearnerUplift, _frame

REPO = Path(__file__).resolve().parents[1]
COLS = list(model_inputs())
ARMS = ("call", "sms_payment_link", "email")
CUT = datetime(2026, 8, 15)
# context at the decision, same sources as the label (contact_history, promises_to_pay); never the decision's own contact
CONTEXT_COLS = ["pending_ptp", "ptp_due_in_days", "n_out_7d", "n_out_30d", "n_rpc_30d", "days_since_contact", "paid_prev7"]
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
            tau[f == i] = LGBMRegressor(n_estimators=200, num_leaves=7, min_child_samples=1000, learning_rate=0.03, reg_lambda=20.0, colsample_bytree=0.8, verbose=-1).fit(X[f != i], phi[f != i]).predict(X[f == i])
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
        print(label, arm, {k: v for k, v in res[-1].items() if k not in ("blp",)}, {k: round(v, 4) for k, v in b.items()}, flush=True)
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
            m = TLearnerUplift(ACTIONS, seed=seed).fit(fit[COLS], action=fit.action, paid_14d=fit.paid_14d, is_random_assignment=pd.Series(True, index=fit.index))
            lift = m.uplift(ev[COLS])
            contacts = [a.value for a in m.actions if a is not Action.WAIT]
            for name in per_seed:
                arm = (ev.action == "call").to_numpy() if name == "call" else ~wait
                both = arm | wait
                score = last[name] = (lift["call"] if name == "call" else lift[contacts].max(axis=1)).to_numpy()
                per_seed[name].append(gate_qini(score[both], arm[both].astype(float), ev.paid_14d.to_numpy(float)[both]))
        row: dict[str, Any] = {"window": f"{s:%d %b} to {min(e, datetime(2026, 9, 14)):%d %b}", "rows": len(ev), "validation": s == datetime(2026, 7, 15)}
        for name, v in per_seed.items():
            arm = (ev.action == "call").to_numpy() if name == "call" else ~wait
            both = arm | wait
            m_score = last[name][both]  # last seed's scores: the bootstrap SD is for sampling noise, the seed spread is reported separately
            sd = case_bootstrap(ev.case_id[both], lambda w, m_score=m_score, arm=arm, both=both: gate_qini(m_score, arm[both].astype(float), ev.paid_14d.to_numpy(float)[both], w), reps=100).std()
            row[name] = {"mean_over_seeds": float(np.mean(v)), "seed_min": float(np.min(v)), "seed_max": float(np.max(v)), "boot_sd": float(sd)}
        out.append(row)
        print(row, flush=True)
    return out


CTX2 = ["pending_ptp", "ptp_due_in_days", "n_out_7d", "n_out_30d", "n_rpc_30d", "days_since_contact", "last_rpc", "last_ptp_made", "paid_prev7", "weekday"]
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
    prof = d.assign(keep=keep, is_arm=t_all).groupby(["is_arm", "keep"])[["max_dpd", "pending_ptp", "n_out_7d"]].mean().round(2)
    all_ate = case_bootstrap(d.case_id, lambda w: (w * ps.phi.to_numpy()).sum() / w.sum(), reps=200)
    dk = d[keep].reset_index(drop=True)
    ps2 = crossfit(dk, cols, arm, outcome=col, binary=binary, seed=1)
    phi, t = ps2.phi.to_numpy(), ps2.t.to_numpy()
    y = dk[col].to_numpy(float)
    ate = case_bootstrap(dk.case_id, lambda w: (w * phi).sum() / w.sum(), reps=300)
    f = folds(dk.case_id, 5, seed=2)
    X, tau = _frame(dk[cols]), np.zeros(len(dk))
    for i in range(5):
        tau[f == i] = LGBMRegressor(n_estimators=200, num_leaves=7, min_child_samples=1000, learning_rate=0.03, reg_lambda=20.0, colsample_bytree=0.8, verbose=-1).fit(X[f != i], phi[f != i]).predict(X[f == i])
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
            {"band": f"{lo + 1}-{hi}", "n": int(m.sum()), "arm_share": float(t[m].mean()), "dr_ate": float(phi[m].mean()), "naive": float(y[m & (t == 1)].mean() - y[m & (t == 0)].mean())}
            for lo, hi in DPD_BANDS
            if (m := (dk.max_dpd.to_numpy() > lo) & (dk.max_dpd.to_numpy() <= hi)).sum() > 500 and 0 < t[m].mean() < 1
        ]
    print(label, arm, name, {k: (round(v, 4) if isinstance(v, float) else v) for k, v in out.items() if k in ("arm_kept", "wait_kept", "ate_untrimmed", "naive_trimmed", "ate", "ate_ci", "oof_dr_qini", "oof_dr_qini_ci", "random_noise")}, {k: round(v, 3) for k, v in out["blp"].items()}, flush=True)
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
    h = conn.sql("select contact_id as decision_id, coalesce(link_payment_flag, false) or coalesce(app_payment_after_contact_flag, false) or coalesce(payment_taken_flag, false) as flagged from silver.contact_history").df()
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
            exp[f == i] = LGBMClassifier(n_estimators=200, num_leaves=15, min_child_samples=300, learning_rate=0.05, verbose=-1).fit(X[tr], d.cured_30d[tr].astype(int)).predict_proba(X[f == i])[:, 1]
        fl = d.flagged.to_numpy()
        diff = case_bootstrap(d.case_id[fl], lambda w, fl=fl, d=d, exp=exp: (w * (d.cured_30d.to_numpy(float)[fl] - exp[fl])).sum() / w.sum(), reps=200)
        tie.append({"arm": arm, "flagged": int(fl.sum()), "cured_30d_flagged": float(d.cured_30d[fl].mean()), "expected_from_unflagged": float(exp[fl].mean()), "diff": float(d.cured_30d[fl].mean() - exp[fl].mean()), "diff_ci": np.quantile(diff, [0.025, 0.975]).tolist(), "unflagged_rate": float(d.cured_30d[~fl].mean())})
        print("tiebreak", tie[-1], flush=True)
    Path(out_path).write_text(json.dumps({"studies": res, "tiebreak_cure": tie}, indent=1, default=float))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--warehouse", default=str(REPO / "data" / "warehouse" / "kept.duckdb"))
    ap.add_argument("--out", default=str(REPO / "data" / "exports" / "reports" / "uplift_diagnostics.json"))
    ap.add_argument("--part", type=int, default=1, help="1: Step 0 on the old rows; 2: overlap x clean outcome, both row sets")
    args = ap.parse_args()
    conn = duckdb.connect(args.warehouse, read_only=True)
    conn.execute("set memory_limit = '4GB'; set threads = 4")
    if args.part == 2:
        part2(conn, args.out.replace(".json", "_part2.json"))
        return
    rows = load(conn)
    ctx_cols = COLS + CONTEXT_COLS
    res: dict[str, Any] = {}
    prof = rows.groupby("action").agg(n=("paid_14d", "size"), paid=("paid_14d", "mean"), pending_ptp=("pending_ptp", "mean"), contacted_prev7=("n_out_7d", lambda s: (s > 0).mean()), paid_prev7=("paid_prev7", "mean"), covered=("covered", "mean"))
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
