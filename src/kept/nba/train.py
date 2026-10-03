"""`kept train`: fit the T-learner on randomly assigned decisions, check it on later ones.

Rows: features_train.training_rows (paid_14d_known only) joined to features_train.case_features at
as_of = decision_at - 1 second. Build both with
`dbt build --select path:models/features --vars '{training_spine: true}'`.
Time split: fit on decisions before `cutoff`, then on decisions from `cutoff` on: Qini per action vs
WAIT, and the same for the legacy strategy's recommendation (collections_cases.nba_recommendation_last
as a 0/1 targeting score), plus "any contact vs WAIT". The plan's check (Q7) is model > legacy.
`noise_*` is the standard deviation of Qini under random rankings: differences below about two of
those are noise.
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
from kept.nba.legacy import legacy_to_action
from kept.nba.uplift import TLearnerUplift, qini_coefficient

# what the randomised data can teach: promise/plan/hardship actions are never randomised
ACTIONS = (Action.WAIT, Action.EMAIL, Action.PUSH, Action.SMS_PAYMENT_LINK, Action.CALL)


def load_rows(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    cols = ", ".join(f"f.{n}" for n in model_inputs())
    return conn.sql(f"""
        select t.decision_id, t.case_id, t.decision_at, t.action, t.paid_14d,
               c.nba_recommendation_last, {cols}
        from features_train.training_rows t
        join features_train.case_features f
            on f.case_id = t.case_id and f.as_of = t.decision_at - interval 1 second
        join silver.collections_cases c on c.case_id = t.case_id
        where t.paid_14d_known
        order by t.decision_at, t.decision_id""").df()


def train(rows: pd.DataFrame, *, cutoff: datetime, seed: int = 0) -> tuple[TLearnerUplift, dict[str, float]]:
    """Fit on rows before cutoff; metrics on rows from cutoff (see the module docstring)."""
    rng = np.random.default_rng(seed)
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
    legacy = late["nba_recommendation_last"].map(lambda c: (a := legacy_to_action(c)) and a.value)
    y = late.paid_14d.to_numpy(dtype=int)
    metrics: dict[str, float] = {"rows_train": float(early.sum()), "rows_test": float(len(late))}
    wait = (late.action == Action.WAIT.value).to_numpy()
    contacts = [a.value for a in ACTIONS[1:]]
    arms = {a: (late.action == a).to_numpy() for a in contacts}
    arms["any_contact"] = ~wait
    for name, arm in arms.items():
        both = arm | wait
        if not (arm.any() and wait.any()):
            continue
        t, yy = arm[both].astype(int), y[both]
        score = lift[contacts].max(axis=1) if name == "any_contact" else lift[name]
        target = legacy.isin(contacts) if name == "any_contact" else legacy == name
        metrics[f"qini_{name}"] = qini_coefficient(score.to_numpy()[both], t, yy)
        metrics[f"qini_legacy_{name}"] = _qini_ties(target.to_numpy(dtype=float)[both], t, yy, rng)
        metrics[f"noise_{name}"] = float(
            np.std([qini_coefficient(rng.random(len(t)), t, yy) for _ in range(100)])
        )
    metrics["paid_rate_test"] = float(np.mean(late.paid_14d)) if len(late) else float("nan")
    return model, metrics


def _qini_ties(
    score: np.ndarray, treated: np.ndarray, outcome: np.ndarray, rng: np.random.Generator
) -> float:
    """Qini of a score with ties (the legacy 0/1 targeting), averaged over random tie-breaks."""
    return float(
        np.mean(
            [qini_coefficient(score + 1e-9 * rng.random(len(score)), treated, outcome) for _ in range(20)]
        )
    )


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
