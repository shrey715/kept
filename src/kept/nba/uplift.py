"""Stage 4: one LightGBM model per action (T-learner) predicting paid_14d,
trained on randomly assigned cases only; checked with Qini on the hold-out.

Training rows are contact attempts (contact_history) with action = treatment_to_action(
treatment_code, channel) and features as of contact_ts_utc. "Randomly assigned" comes from
collections_cases.assignment_method / test_cell (champion / challenger_X / hold-out);
TBC: which assignment_method values mean random (rule_based does not).
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

from kept.contracts.enums import Action


class TLearnerUplift:
    """Implements kept.contracts.interfaces.UpliftScorer."""

    model_version: str

    def __init__(
        self,
        actions: Sequence[Action] = tuple(Action),
        *,
        params: dict[str, object] | None = None,
        seed: int = 0,
    ) -> None:
        raise NotImplementedError("Track D")

    def fit(
        self, X: pd.DataFrame, *, action: pd.Series, paid_14d: pd.Series, is_random_assignment: pd.Series
    ) -> TLearnerUplift:
        """Train one model per action on rows where is_random_assignment is True.
        X containing any denied column -> ValueError. An action with no random rows -> ValueError."""
        raise NotImplementedError("Track D")

    def predict_proba(self, features: pd.DataFrame) -> pd.DataFrame:
        """Columns = action values, rows aligned with input index, values in [0, 1].
        Not fitted -> RuntimeError."""
        raise NotImplementedError("Track D")

    def uplift(self, features: pd.DataFrame, *, baseline: Action = Action.WAIT) -> pd.DataFrame:
        """predict_proba minus the baseline column; baseline column is all zeros."""
        # NOTE: p_kept for promise/plan actions is a separate model; see ranking.score_actions.
        raise NotImplementedError("Track D")


def qini_curve(
    uplift_score: np.ndarray, treated: np.ndarray, outcome: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """(fraction targeted, incremental gains) sorted by score descending, starting at (0, 0).
    gain(k) = Y_t(k) - Y_c(k) * N_t(k) / N_c(k), where the control term is 0 while N_c(k) == 0.
    Y_t/Y_c = positive outcomes among treated/control in the top k; N_t/N_c = counts.
    treated and outcome must be binary; lengths must match; else ValueError."""
    raise NotImplementedError("Track D")


def qini_coefficient(uplift_score: np.ndarray, treated: np.ndarray, outcome: np.ndarray) -> float:
    """Trapezoid area under (fraction, gain / n) minus the area under the straight line from
    (0, 0) to (1, gain(n) / n). > 0 means better than random targeting."""
    raise NotImplementedError("Track D")
