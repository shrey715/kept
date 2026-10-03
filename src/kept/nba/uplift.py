"""Stage 4: one LightGBM model per action (T-learner) predicting paid_14d,
trained on randomly assigned cases only; checked with Qini on the hold-out.

Training rows (dbt features.training_rows) are contact attempts with action = treatment_to_action(
treatment_code, channel), and WAIT = weekly check-in days with no outbound contact, all on
randomly assigned cases (collections_cases.assignment_method == 'random'), with features a second
before each decision. The no_contact_holdout cell delays contact rather than withholding it, so
it is not a WAIT arm on its own.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd

from kept.contracts.enums import Action, PayrollFrequency
from kept.features.store import assert_no_denied

# Small, regularised trees: per-arm models that overfit make the uplift (a difference of two
# models) noisy. Chosen on real data (3 Oct): call Qini 0.0067 vs 0.0042 with 200 trees / 15 leaves.
DEFAULT_PARAMS: dict[str, Any] = {
    "n_estimators": 100,
    "learning_rate": 0.05,
    "num_leaves": 7,
    "min_child_samples": 300,
    "reg_lambda": 5.0,
    "subsample": 0.8,
    "subsample_freq": 1,
    "colsample_bytree": 0.8,
    "verbose": -1,
}


# category features: fixed levels so training and serving encode them the same way
_CATEGORIES = {"pay_frequency": [p.value for p in PayrollFrequency]}


def _frame(X: pd.DataFrame) -> pd.DataFrame:
    """LightGBM dtypes from warehouse rows or FeatureVector dicts: categories with fixed levels,
    bools / decimals / None (object columns) as floats with NaN for missing."""
    out: dict[str, Any] = {}
    for c in X.columns:
        col = X[c]
        if c in _CATEGORIES:
            out[c] = pd.Categorical(col.where(col.notna(), None).astype(object), categories=_CATEGORIES[c])
        elif col.dtype == object or col.dtype == bool:
            out[c] = col.astype(object).where(col.notna(), np.nan).astype(float)
        else:
            out[c] = col
    return pd.DataFrame(out, index=X.index)


class TLearnerUplift:
    """Implements kept.contracts.interfaces.UpliftScorer."""

    model_version: str

    def __init__(
        self,
        actions: Sequence[Action] = tuple(Action),
        *,
        params: dict[str, Any] | None = None,
        seed: int = 0,
    ) -> None:
        self.actions = tuple(actions)
        self.params = {**DEFAULT_PARAMS, **(params or {}), "random_state": seed}
        self.model_version = "unfitted"
        self._models: dict[Action, Any] = {}  # LGBMClassifier, or a float when one class only
        self._columns: list[str] = []

    def fit(
        self, X: pd.DataFrame, *, action: pd.Series, paid_14d: pd.Series, is_random_assignment: pd.Series
    ) -> TLearnerUplift:
        """Train one model per action on rows where is_random_assignment is True.
        X containing any denied column -> ValueError. An action with no random rows -> ValueError."""
        assert_no_denied(X)
        from lightgbm import LGBMClassifier

        X = _frame(X)
        keep = is_random_assignment.to_numpy(dtype=bool)
        Xr, ar, yr = X[keep], action[keep].to_numpy(), paid_14d[keep].to_numpy(dtype=int)
        models: dict[Action, Any] = {}
        for a in self.actions:
            rows = ar == a.value
            if not rows.any():
                raise ValueError(f"no randomly assigned rows for action {a.value}")
            y = yr[rows]
            if y.min() == y.max():  # one class only: LightGBM can't fit it, the rate is the answer
                models[a] = float(y[0])
            else:
                models[a] = LGBMClassifier(**self.params).fit(Xr[rows], y)
        self._models, self._columns = models, list(X.columns)
        digest = hashlib.sha256(
            repr(
                (sorted(self.params.items()), self._columns, [a.value for a in self.actions], len(Xr))
            ).encode()
        ).hexdigest()
        self.model_version = f"tlearner-lgbm-{digest[:12]}"
        return self

    def predict_proba(self, features: pd.DataFrame) -> pd.DataFrame:
        """Columns = action values, rows aligned with input index, values in [0, 1].
        Not fitted -> RuntimeError."""
        if not self._models:
            raise RuntimeError("TLearnerUplift is not fitted")
        X = _frame(features[self._columns])
        out = {
            a.value: np.full(len(X), m) if isinstance(m, float) else m.predict_proba(X)[:, 1]
            for a, m in self._models.items()
        }
        return pd.DataFrame(out, index=features.index).clip(0.0, 1.0)

    def uplift(self, features: pd.DataFrame, *, baseline: Action = Action.WAIT) -> pd.DataFrame:
        """predict_proba minus the baseline column; baseline column is all zeros."""
        # NOTE: p_kept for promise/plan actions is a separate model; see ranking.score_actions.
        if baseline not in self.actions:
            raise ValueError(f"baseline {baseline.value} is not one of the fitted actions")
        proba = self.predict_proba(features)
        return proba.sub(proba[baseline.value], axis=0)

    def contributions(
        self, row: pd.DataFrame, action: Action, *, baseline: Action = Action.WAIT
    ) -> dict[str, float]:
        """TreeSHAP (LightGBM's own pred_contrib) for one row: how much each feature moves
        P(paid | action) - P(paid | baseline) away from the average case, in probability units.
        Each model's log-odds contribution c_i becomes sigmoid(L) - sigmoid(L - c_i) (L = the
        row's full log-odds), then baseline is subtracted from action.
        ponytail: leave-one-out in probability space keeps sign and size but doesn't sum exactly
        to the uplift; use the shap package's probability explainer if exact additivity matters."""
        if len(row) != 1:
            raise ValueError("contributions takes exactly one row")
        X = _frame(row[self._columns])
        out = self._prob_contrib(action, X) - self._prob_contrib(baseline, X)
        return {c: float(v) for c, v in zip(self._columns, out, strict=True)}

    def _prob_contrib(self, a: Action, X: pd.DataFrame) -> np.ndarray:
        m = self._models[a]
        if isinstance(m, float):  # constant model: no feature moves it
            return np.zeros(len(self._columns))
        contrib = np.asarray(m.predict_proba(X, pred_contrib=True))[0]
        logit, c = contrib.sum(), contrib[:-1]  # last entry is the bias

        def sig(z: np.ndarray | float) -> np.ndarray:
            return np.asarray(1 / (1 + np.exp(-np.asarray(z, dtype=float))))

        return np.asarray(sig(logit) - sig(logit - c), dtype=float)


def qini_curve(
    uplift_score: np.ndarray, treated: np.ndarray, outcome: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """(fraction targeted, incremental gains) sorted by score descending, starting at (0, 0).
    gain(k) = Y_t(k) - Y_c(k) * N_t(k) / N_c(k), where the control term is 0 while N_c(k) == 0.
    Y_t/Y_c = positive outcomes among treated/control in the top k; N_t/N_c = counts.
    treated and outcome must be binary; lengths must match; else ValueError."""
    score, t, y = (np.asarray(v) for v in (uplift_score, treated, outcome))
    if not len(score) == len(t) == len(y):
        raise ValueError("uplift_score, treated and outcome must have the same length")
    if not (np.isin(t, (0, 1)).all() and np.isin(y, (0, 1)).all()):
        raise ValueError("treated and outcome must be 0/1")
    order = np.argsort(-score, kind="stable")
    t, y = t[order].astype(float), y[order].astype(float)
    n_t, n_c = np.cumsum(t), np.cumsum(1 - t)
    y_t, y_c = np.cumsum(y * t), np.cumsum(y * (1 - t))
    with np.errstate(divide="ignore", invalid="ignore"):
        control = np.where(n_c > 0, y_c * n_t / n_c, 0.0)
    gain = np.concatenate([[0.0], y_t - control])
    frac = np.arange(len(t) + 1) / len(t)
    return frac, gain


def qini_coefficient(uplift_score: np.ndarray, treated: np.ndarray, outcome: np.ndarray) -> float:
    """Trapezoid area under (fraction, gain / n) minus the area under the straight line from
    (0, 0) to (1, gain(n) / n). > 0 means better than random targeting."""
    frac, gain = qini_curve(uplift_score, treated, outcome)
    g = gain / (len(frac) - 1)
    return float(np.trapezoid(g, frac) - 0.5 * g[-1])
