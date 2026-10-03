"""Stage 4: one LightGBM model per action (T-learner) predicting paid_14d,
trained on randomly assigned cases only; checked with Qini on the hold-out.

Training rows are contact attempts (contact_history) with action = treatment_to_action(
treatment_code, channel) and features as of contact_ts_utc. "Randomly assigned" comes from
collections_cases.assignment_method == 'random' (146,573 cases on 28 Sep 2026; rule_based is
not random). The random-only no_contact_holdout cell is the WAIT arm.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd

from kept.contracts.enums import Action
from kept.features.store import assert_no_denied

# Small, regularised trees: the random-assignment rows are a minority of the data.
DEFAULT_PARAMS: dict[str, Any] = {
    "n_estimators": 200,
    "learning_rate": 0.05,
    "num_leaves": 15,
    "min_child_samples": 50,
    "subsample": 0.8,
    "subsample_freq": 1,
    "colsample_bytree": 0.8,
    "verbose": -1,
}


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
        X = features[self._columns]
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
