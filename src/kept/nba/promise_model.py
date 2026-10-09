"""P(kept | promise) (#79): how likely a promise is to be kept, from what's known when it's made.

Trained on resolved promises (kept vs partially kept or broken), time split. Used to *size and explain*
a promise on the card ("if they agree to this date, 58% chance it's kept; due just before payday, 49%"),
never to rank a promise against other actions: P(kept) is conditional on the customer agreeing, and
we have no data on how often they agree, so it would overstate a promise request.

Inputs only from the promise itself, the customer's earlier promises and salary deposit dates. None is a
protected attribute or a proxy (tests/nba/test_promise_model.py checks SOURCE_COLUMNS against the contract).
Not `ptp_to_overdue_ratio`: in this data a full-balance promise is all but always kept, which took test AUC
from 0.63 to 0.92 and would steer every card to "promise the whole balance" (docs/reports/evidence.md §3).
"""

from __future__ import annotations

import pickle
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

FEATURES = (
    "days_to_due",  # due date - promise date
    "dpd",  # days past due at the time
    "prior_broken_90d",  # the customer's promises broken in the 90 days before
    "prior_kept_ratio",  # kept / resolved of the customer's earlier promises (None if none)
    "days_after_pay",  # due date - the last salary deposit on or before it (None if unknown)
    "days_before_next_pay",  # the next salary deposit after the due date - due date (None if unknown)
)
SOURCE_COLUMNS = (
    "promises_to_pay.days_to_due_at_creation",
    "promises_to_pay.dpd_at_creation",
    "promises_to_pay.ptp_status",
    "promises_to_pay.status_ts",
    "promises_to_pay.ptp_created_ts",
    "promises_to_pay.ptp_due_date",
    "salary_credit_history.first_credit_date",
    "salary_credit_history.last_credit_date",
)
PERIOD_DAYS = {"weekly": 7, "biweekly": 14, "semi_monthly": 15, "monthly": 30}  # semi-monthly: 15 days here
CUTOFF = datetime(2026, 7, 15)  # fit on promises made before, check on promises made after
# the kept rate fell from ~63% (2016 to May 2026) to ~35% (Jun to Sep 2026): the trees learn the ranking from
# the long history, then the last CALIBRATE_DAYS before the cutoff map scores to today's rate (isotonic),
# so the card's "N% chance" is honest (worst decile gap 22 -> 7 points)
CALIBRATE_DAYS = 60


def load(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """One row per resolved promise with FEATURES (point in time) and kept (0/1)."""
    return conn.sql("""
        with pr as (
            select ptp_id, crm_customer_id, ptp_created_ts as created, ptp_due_date as due, ptp_status,
                   status_ts, days_to_due_at_creation as days_to_due,
                   dpd_at_creation as dpd
            from silver.promises_to_pay where ptp_status in ('kept', 'partially_kept', 'broken')),
        prior as (
            select p.ptp_id,
                   count(*) filter (
                       where q.ptp_status = 'broken' and q.status_ts > p.created - interval 90 day
                   ) as prior_broken_90d,
                   avg((q.ptp_status = 'kept')::int) as prior_kept_ratio
            from pr p join pr q
                on q.crm_customer_id = p.crm_customer_id and q.status_ts < p.created
            group by p.ptp_id),
        pay as (select distinct crm_customer_id, unnest([first_credit_date, last_credit_date]) as d
                from silver.salary_credit_history where crm_customer_id is not null),
        lst as (select p.ptp_id, max(y.d) as lp from pr p join pay y on y.crm_customer_id = p.crm_customer_id
                and y.d between p.due - 40 and p.due group by 1),
        nxt as (select p.ptp_id, min(y.d) as np from pr p join pay y on y.crm_customer_id = p.crm_customer_id
                and y.d > p.due and y.d <= p.due + 40 group by 1)
        select p.ptp_id, p.created, p.days_to_due, p.dpd,
               coalesce(r.prior_broken_90d, 0) as prior_broken_90d, r.prior_kept_ratio,
               p.due - l.lp as days_after_pay, n.np - p.due as days_before_next_pay,
               (p.ptp_status = 'kept')::int as kept
        from pr p left join prior r using (ptp_id) left join lst l using (ptp_id)
        left join nxt n using (ptp_id)
        order by p.created""").df()


class PromiseModel:
    def __init__(self, model: Any, calibrator: Any = None) -> None:
        self._model = model
        self._calibrator = calibrator

    def p_kept(self, rows: list[dict[str, Any]]) -> np.ndarray:
        X = pd.DataFrame([{f: r.get(f) for f in FEATURES} for r in rows]).astype(float)
        p = np.asarray(self._model.predict_proba(X)[:, 1])
        calibrator = getattr(self, "_calibrator", None)  # models pickled before calibration have none
        return np.asarray(calibrator.predict(p)) if calibrator is not None else p


def train(rows: pd.DataFrame, *, cutoff: datetime = CUTOFF) -> tuple[PromiseModel, dict[str, float]]:
    """LightGBM on promises made before cutoff minus CALIBRATE_DAYS, isotonic calibration on the
    CALIBRATE_DAYS before cutoff; AUC, Brier and calibration on the promises from cutoff on."""
    from lightgbm import LGBMClassifier
    from sklearn.isotonic import IsotonicRegression  # type: ignore[import-untyped]
    from sklearn.metrics import brier_score_loss, roc_auc_score  # type: ignore[import-untyped]

    early = (rows.created < cutoff).to_numpy()
    fit = (rows.created < cutoff - timedelta(days=CALIBRATE_DAYS)).to_numpy()
    calib = early & ~fit
    X = rows[list(FEATURES)].astype(float)
    m = LGBMClassifier(n_estimators=200, num_leaves=15, min_child_samples=200, learning_rate=0.05, verbose=-1)
    m.fit(X[fit], rows.kept[fit])
    iso = IsotonicRegression(out_of_bounds="clip").fit(
        np.asarray(m.predict_proba(X[calib]))[:, 1], rows.kept[calib]
    )
    model = PromiseModel(m, iso)
    p = np.asarray(iso.predict(np.asarray(m.predict_proba(X[~early]))[:, 1]))
    y = rows.kept[~early].to_numpy()
    bins = np.clip((p * 10).astype(int), 0, 9)
    gaps = [abs(p[bins == b].mean() - y[bins == b].mean()) for b in range(10) if (bins == b).sum() >= 200]
    return model, {
        "rows_train": float(early.sum()),
        "rows_test": float((~early).sum()),
        "auc": float(roc_auc_score(y, p)),
        "brier": float(brier_score_loss(y, p)),
        "calibration_max_gap": float(max(gaps)),
        "kept_rate_test": float(y.mean()),
    }


def serving_row(
    *,
    due: date,
    today: date,
    payday: date,
    frequency: str | None,
    dpd: int | None,
    prior_broken_90d: int | None,
    prior_kept_ratio: float | None,
) -> dict[str, Any]:
    """The same FEATURES for a promise Kept is about to propose."""
    after = (due - payday).days
    period = PERIOD_DAYS.get(frequency or "")
    return {
        "days_to_due": (due - today).days,
        "dpd": dpd,
        "prior_broken_90d": prior_broken_90d or 0,
        "prior_kept_ratio": prior_kept_ratio,
        "days_after_pay": after,
        "days_before_next_pay": period - after if period else None,
    }


def save(model: PromiseModel, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pickle.dumps(model))


def load_model(path: Path) -> PromiseModel | None:
    return (
        pickle.loads(path.read_bytes()) if path.exists() else None
    )  # our own file, from kept train-promises
