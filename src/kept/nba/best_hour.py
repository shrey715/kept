# ruff: noqa: E501  (docstrings)
"""P(right-party contact | the call's local hour and weekday, the case's inputs): the hour a call is likeliest to be answered.

Used only by the nightly booking (`CallCapacity.book_best`, switched on by `kept score --best-hour`); it never ranks actions.
Inputs are the uplift model's 17 registry inputs (`model_inputs()`, none protected or a proxy) plus the slot's hour and weekday
in the customer's own time zone. Trained on outbound calls to randomly assigned cases, time split like the uplift model
(`kept train-best-hour`). docs/reports/best_hour.md has the method and the replay.
"""

from __future__ import annotations

import pickle
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from kept.contracts.feature_registry import model_inputs
from kept.features.store import assert_no_denied
from kept.nba.uplift import _frame

CUTOFF = datetime(2026, 8, 15)  # fit on calls before, check on calls from here (the uplift model's split)
PARAMS: dict[str, Any] = dict(
    n_estimators=200, num_leaves=15, min_child_samples=300, learning_rate=0.05, colsample_bytree=0.8,
    subsample=0.8, subsample_freq=1, verbose=-1, deterministic=True, force_row_wise=True, random_state=0,
)  # fmt: skip


def slot_columns() -> list[str]:
    return [*model_inputs(), "hour", "weekday"]


def load(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """One row per outbound call on a randomly assigned case: the inputs a second before it, its local hour and weekday, and
    whether it reached the right party."""
    from kept.nba.train import load_rows

    calls = load_rows(conn)
    calls = calls[calls.action == "call"]
    h = conn.sql(
        "select contact_id as decision_id, contact_hour_local as hour, dayofweek(contact_ts_local) as dow,"
        " coalesce(rpc_flag, false) as rpc from silver.contact_history where direction = 'outbound'"
    ).df()
    d = calls.merge(h, on="decision_id").dropna(subset=["hour", "dow"])
    d["hour"] = d.hour.astype(int)
    d["weekday"] = (d.dow.astype(int) - 1) % 7  # duckdb: Sunday 0 -> Monday 0
    return d.reset_index(drop=True)


class BestHourModel:
    model_version: str

    def __init__(self, model: Any, version: str) -> None:
        self._model, self.model_version = model, version

    def p_rpc(self, features: pd.DataFrame, slots: Sequence[tuple[int, int]]) -> np.ndarray:
        """Chance a call reaches the right party, for one case (`features`: one row of `model_inputs()`), at each
        (local hour, weekday) slot."""
        x = pd.concat([features[list(model_inputs())]] * len(slots), ignore_index=True)
        x["hour"], x["weekday"] = [h for h, _ in slots], [w for _, w in slots]
        return np.asarray(self._model.predict_proba(_frame(x))[:, 1])


def train(rows: pd.DataFrame, *, cutoff: datetime = CUTOFF) -> tuple[BestHourModel, dict[str, float]]:
    from lightgbm import LGBMClassifier
    from sklearn.metrics import roc_auc_score  # type: ignore[import-untyped]

    X = _frame(rows[slot_columns()])
    assert_no_denied(X)  # no protected attribute or proxy reaches the model
    fit = (rows.decision_at < cutoff).to_numpy()
    y = rows.rpc.to_numpy(int)
    m = LGBMClassifier(**PARAMS).fit(X[fit], y[fit])
    p = np.asarray(m.predict_proba(X[~fit]))[:, 1]
    metrics = {
        "calls_fit": float(fit.sum()),
        "calls_test": float((~fit).sum()),
        "rpc_rate_test": float(y[~fit].mean()),
        "auc_test": float(roc_auc_score(y[~fit], p)),
    }
    return BestHourModel(m, f"besthour-lgbm-{cutoff:%Y%m%d}"), metrics


def save(model: BestHourModel, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pickle.dumps(model))


def load_model(path: Path) -> BestHourModel | None:
    return pickle.loads(path.read_bytes()) if path.exists() else None  # our own file, from kept train-best-hour
