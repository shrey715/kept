"""Evaluation and estimation helpers for uplift from non-randomised actions (offline only, never on the serving path).

The bank chose each day's action, so treated and untreated decisions differ. Doubly robust (AIPW) pseudo-outcomes
correct for that: phi = m1 - m0 + t/e (y - m1) - (1-t)/(1-e) (y - m0), with m the outcome models and e the propensity.
mean(phi) is the average effect; a model's ranking is judged by the area between the cumulative sum of phi in its
order and the straight line (`dr_qini`). Rows cluster by case (many decisions per case), so uncertainty comes from
resampling whole cases (`case_bootstrap`), not rows.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import numpy as np
import pandas as pd

from kept.nba.uplift import _frame

NUIS: dict[str, Any] = dict(
    n_estimators=200, num_leaves=15, min_child_samples=300, learning_rate=0.05, colsample_bytree=0.8,
    subsample=0.8, subsample_freq=1, verbose=-1, deterministic=True, force_row_wise=True,
)  # fmt: skip
CLIP = (0.05, 0.95)


def aipw(y: np.ndarray, t: np.ndarray, m1: np.ndarray, m0: np.ndarray, e: np.ndarray) -> np.ndarray:
    e = np.clip(e, *CLIP)
    return m1 - m0 + t / e * (y - m1) - (1 - t) / (1 - e) * (y - m0)  # type: ignore[no-any-return]


class Nuisance:
    """Outcome models for the arm and for waiting, plus P(arm | x) among those two, fitted on one frame."""

    def __init__(self, cols: Sequence[str], arm: str, outcome: str = "paid_14d", seed: int = 0, *, binary: bool = True) -> None:
        self.cols, self.arm, self.outcome, self.seed, self.binary = list(cols), arm, outcome, seed, binary

    def fit(self, df: pd.DataFrame) -> Nuisance:
        from lightgbm import LGBMClassifier, LGBMRegressor

        d = df[df.action.isin([self.arm, "wait"])]
        X, t, y = _frame(d[self.cols]), (d.action == self.arm).to_numpy(), d[self.outcome].to_numpy(float)
        p = {**NUIS, "random_state": self.seed}
        out = LGBMClassifier if self.binary else LGBMRegressor
        self.m1 = out(**p).fit(X[t], y[t].astype(int) if self.binary else y[t])
        self.m0 = out(**p).fit(X[~t], y[~t].astype(int) if self.binary else y[~t])
        self.e = LGBMClassifier(**p).fit(X, t.astype(int))
        return self

    def pseudo(self, df: pd.DataFrame) -> tuple[np.ndarray, pd.DataFrame]:
        """(mask of rows in arm or wait, frame with y, t, m1, m0, e, phi for those rows)."""
        mask = df.action.isin([self.arm, "wait"]).to_numpy()
        d = df[mask]
        X = _frame(d[self.cols])
        y, t = d[self.outcome].to_numpy(float), (d.action == self.arm).to_numpy(float)
        m1, m0 = (m.predict_proba(X)[:, 1] if self.binary else m.predict(X) for m in (self.m1, self.m0))
        e = self.e.predict_proba(X)[:, 1]
        out = pd.DataFrame({"y": y, "t": t, "m1": m1, "m0": m0, "e": e, "phi": aipw(y, t, m1, m0, e)}, index=d.index)
        return mask, out


def folds(case_ids: pd.Series, k: int, seed: int = 0) -> np.ndarray:
    """Fold number per row, whole cases together."""
    codes = pd.factorize(case_ids)[0]
    rng = np.random.default_rng(seed)
    return rng.permutation(codes.max() + 1)[codes] % k  # type: ignore[no-any-return]


def crossfit(df: pd.DataFrame, cols: Sequence[str], arm: str, *, k: int = 5, seed: int = 0, outcome: str = "paid_14d", binary: bool = True) -> pd.DataFrame:
    """Out-of-fold pseudo-outcomes for the rows in arm or wait (nuisance models never see the row's case)."""
    f = folds(df.case_id, k, seed)
    parts = []
    for i in range(k):
        n = Nuisance(cols, arm, outcome, seed, binary=binary).fit(df[f != i])
        parts.append(n.pseudo(df[f == i])[1])
    return pd.concat(parts).sort_index()


def dr_qini(score: np.ndarray, phi: np.ndarray, w: np.ndarray | None = None) -> float:
    """Area between the doubly robust gain curve in `score` order and the straight line to its end (> 0: better than random)."""
    w = np.ones(len(phi)) if w is None else w
    o = np.argsort(-score, kind="stable")
    tot = w.sum()
    x = np.concatenate([[0.0], np.cumsum(w[o])]) / tot
    g = np.concatenate([[0.0], np.cumsum((w * phi)[o])]) / tot
    return float(np.trapezoid(g, x) - 0.5 * g[-1])


def case_bootstrap(case_ids: pd.Series, fn: Callable[[np.ndarray], Any], *, reps: int = 200, seed: int = 0) -> np.ndarray:
    """fn(row_weights) on `reps` resamples of whole cases (weights = how often the row's case was drawn). Returns an array of the results."""
    codes = pd.factorize(case_ids)[0]
    n = codes.max() + 1
    rng = np.random.default_rng(seed)
    return np.asarray([fn(np.bincount(rng.integers(0, n, n), minlength=n)[codes].astype(float)) for _ in range(reps)])


def blp(phi: np.ndarray, tau: np.ndarray, case_ids: pd.Series) -> dict[str, float]:
    """Best-linear-predictor test (Chernozhukov et al.): phi ~ a + b * (tau - mean tau), case-clustered SEs.
    b > 0 with a small p means the CATE predictions carry real heterogeneity; b near 1 means they are calibrated."""
    x = np.column_stack([np.ones(len(phi)), tau - tau.mean()])
    xtx_inv = np.linalg.inv(x.T @ x)
    beta = xtx_inv @ x.T @ phi
    u = x * (phi - x @ beta)[:, None]
    cl = pd.DataFrame(u).groupby(pd.factorize(case_ids)[0]).sum().to_numpy()
    cov = xtx_inv @ (cl.T @ cl) @ xtx_inv
    se = np.sqrt(np.diag(cov))
    return {"ate": float(beta[0]), "ate_se": float(se[0]), "slope": float(beta[1]), "slope_se": float(se[1]), "slope_t": float(beta[1] / se[1])}


def gate_qini(score: np.ndarray, t: np.ndarray, y: np.ndarray, w: np.ndarray | None = None) -> float:
    """`kept.nba.uplift.qini_coefficient` (treated against untreated directly, as the gate does) with optional row weights,
    so a case bootstrap can reuse it. With w = 1 it returns the same number."""
    w = np.ones(len(y)) if w is None else w
    o = np.argsort(-score, kind="stable")
    w, t, y = w[o], t[o].astype(float), y[o].astype(float)
    n_t, n_c, y_t, y_c = np.cumsum(w * t), np.cumsum(w * (1 - t)), np.cumsum(w * y * t), np.cumsum(w * y * (1 - t))
    with np.errstate(divide="ignore", invalid="ignore"):
        gain = np.concatenate([[0.0], y_t - np.where(n_c > 0, y_c * n_t / n_c, 0.0)])
    tot = w.sum()
    x, g = np.concatenate([[0.0], np.cumsum(w)]) / tot, gain / tot
    return float(np.trapezoid(g, x) - 0.5 * g[-1])
