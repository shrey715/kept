"""`kept train`: fit the T-learner on randomly assigned decisions, check it on later ones.

Rows: features_train.training_rows (paid_14d_known only) joined to features_train.case_features at
as_of = decision_at - 1 second. Build both with
`dbt build --select path:models/features --vars '{training_spine: true}'`.
Time split: fit on decisions before `cutoff`, Qini per action vs WAIT on decisions from `cutoff` on.
"""

from __future__ import annotations

import pickle
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from kept.contracts.enums import Action
from kept.contracts.feature_registry import model_inputs
from kept.nba.uplift import TLearnerUplift, qini_coefficient

# what the randomised data can teach: promise/plan/hardship actions are never randomised
ACTIONS = (Action.WAIT, Action.EMAIL, Action.PUSH, Action.SMS_PAYMENT_LINK, Action.CALL)


def load_rows(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    cols = ", ".join(f"f.{n}" for n in model_inputs())
    return conn.sql(f"""
        select t.decision_id, t.case_id, t.decision_at, t.action, t.paid_14d, {cols}
        from features_train.training_rows t
        join features_train.case_features f
            on f.case_id = t.case_id and f.as_of = t.decision_at - interval 1 second
        where t.paid_14d_known
        order by t.decision_at, t.decision_id""").df()


def train(rows: pd.DataFrame, *, cutoff: datetime, seed: int = 0) -> tuple[TLearnerUplift, dict[str, float]]:
    """Fit on rows before cutoff; metrics on rows from cutoff: Qini of each action's uplift score
    (that action's rows vs WAIT rows) and the row counts."""
    X = rows[list(model_inputs())]
    early = (rows.decision_at < cutoff).to_numpy()
    model = TLearnerUplift(ACTIONS, seed=seed).fit(
        X[early],
        action=rows.action[early],
        paid_14d=rows.paid_14d[early],
        is_random_assignment=pd.Series(True, index=rows.index[early]),
    )
    late = rows[~early]
    lift = model.uplift(late[X.columns])
    metrics: dict[str, float] = {"rows_train": float(early.sum()), "rows_test": float(len(late))}
    wait = (late.action == Action.WAIT.value).to_numpy()
    for a in ACTIONS[1:]:
        arm = (late.action == a.value).to_numpy()
        both = arm | wait
        if arm.any() and wait.any():
            metrics[f"qini_{a.value}"] = qini_coefficient(
                lift[a.value].to_numpy()[both], arm[both].astype(int), late.paid_14d.to_numpy(dtype=int)[both]
            )
    metrics["paid_rate_test"] = float(np.mean(late.paid_14d)) if len(late) else float("nan")
    return model, metrics


def run(conn: duckdb.DuckDBPyConnection, *, cutoff: datetime, out: Path, seed: int = 0) -> dict[str, Any]:
    """Load, train, pickle the model to `out`, log params/metrics/model to MLflow (./mlruns)."""
    import mlflow

    rows = load_rows(conn)
    model, metrics = train(rows, cutoff=cutoff, seed=seed)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(pickle.dumps(model))
    mlflow.set_experiment("kept-uplift")
    with mlflow.start_run(run_name=model.model_version):
        mlflow.log_params({**model.params, "cutoff": cutoff.isoformat(), "features": len(model_inputs())})
        mlflow.log_metrics(metrics)
        mlflow.log_artifact(str(out))
    return {"model_version": model.model_version, **metrics}
