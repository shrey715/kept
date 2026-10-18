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
# --pool-nudges (#80): the model can't tell these apart per customer (the top one held in about 37% of
# bootstrap resamples), so they can share one "digital nudge" arm, stored under EMAIL; the engine then
# scores push and SMS with it and the ranking picks the cheapest one the customer consented to
NUDGES = (Action.EMAIL, Action.PUSH, Action.SMS_PAYMENT_LINK)
POOLED = (Action.WAIT, Action.EMAIL, Action.CALL)


def pool_nudges(rows: pd.DataFrame) -> pd.DataFrame:
    """Every nudge row (and a legacy nudge recommendation) becomes the one nudge arm."""
    nudge = {a.value: Action.EMAIL.value for a in NUDGES}
    return rows.assign(action=rows.action.replace(nudge))


# decision context (features_train.decision_context), offline studies only: what the bank knew before deciding
CONTEXT_COLS = [
    "pending_ptp", "ptp_due_in_days", "n_out_7d", "n_out_30d", "n_rpc_30d",
    "days_since_contact", "last_rpc", "last_ptp_made", "paid_prev7", "weekday",
]  # fmt: skip


def load_rows(
    conn: duckdb.DuckDBPyConnection, *, source: str = "training_rows", extras: bool = False
) -> pd.DataFrame:
    """The live model's rows. extras=True (offline studies) adds the account-sourced outcomes (paid_clean_14d,
    paid_amt_14d, covered), cured_30d and the context at the decision (features_train.decision_context). With
    extras every row is kept and `covered` says whether its "no" can be trusted; "training_weeks" is the
    one-row-per-case-landmark table."""
    cols = ", ".join(f"f.{n}" for n in model_inputs())
    more = ""
    if extras:
        more = """, t.paid_clean_14d, t.paid_amt_14d, t.covered, t.paid_14d_known,
               coalesce(c.cure_flag and c.cure_date <= cast(t.label_at as date) + 30, false) as cured_30d,
               x.pending_ptp, x.ptp_due_in_days, x.n_out_7d, x.n_out_30d, x.n_rpc_30d, x.days_since_contact,
               x.last_rpc, x.last_ptp_made, x.paid_prev7, x.weekday, c.primary_product, t.crm_customer_id"""
    join_x = "join features_train.decision_context x using (decision_id)" if extras else ""
    where = "where t.paid_14d_known" if not extras else ""
    return conn.sql(f"""
        select t.decision_id, t.case_id, t.decision_at, t.action, t.paid_14d,
               c.nba_recommendation_last, {cols}{more}
        from features_train.{source} t
        join features_train.case_features f
            on f.case_id = t.case_id and f.as_of = t.decision_at - interval 1 second
        join silver.collections_cases c on c.case_id = t.case_id
        {join_x}
        {where}
        order by t.decision_at, t.decision_id""").df()


def train(
    rows: pd.DataFrame, *, cutoff: datetime, seed: int = 0, pooled: bool = False
) -> tuple[TLearnerUplift, dict[str, float]]:
    """Fit on rows before cutoff; metrics on rows from cutoff (see the module docstring).
    pooled: one arm for email, push and SMS (`pool_nudges`)."""
    rows = pool_nudges(rows) if pooled else rows
    X = rows[list(model_inputs())]
    early = (rows.decision_at < cutoff).to_numpy()
    model = TLearnerUplift(POOLED if pooled else ACTIONS, seed=seed).fit(
        X[early],
        action=rows.action[early],
        paid_14d=rows.paid_14d[early],
        is_random_assignment=pd.Series(True, index=rows.index[early]),
    )
    return model, evaluate(model, rows, cutoff=cutoff, seed=seed)


def evaluate(
    model: TLearnerUplift, rows: pd.DataFrame, *, cutoff: datetime, seed: int = 0
) -> dict[str, float]:
    """The test-split metrics for any fitted model, so a champion and a challenger are judged on the
    same rows (decisions from cutoff on)."""
    rng = np.random.default_rng(seed)
    pooled = Action.PUSH not in model.actions
    rows = pool_nudges(rows) if pooled else rows
    X = rows[list(model_inputs())]
    early = (rows.decision_at < cutoff).to_numpy()
    late = rows[~early]
    lift = model.uplift(late[X.columns])
    legacy = late["nba_recommendation_last"].map(lambda c: (a := legacy_to_action(c)) and a.value)
    if pooled:
        legacy = legacy.replace({a.value: Action.EMAIL.value for a in NUDGES})
    y = late.paid_14d.to_numpy(dtype=int)
    metrics: dict[str, float] = {"rows_train": float(early.sum()), "rows_test": float(len(late))}
    wait = (late.action == Action.WAIT.value).to_numpy()
    contacts = [a.value for a in model.actions if a is not Action.WAIT]
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
    return metrics


def promote(challenger: dict[str, float], champion: dict[str, float] | None) -> tuple[bool, str]:
    """Champion/challenger gate (#83): the challenger goes live only if it beats the champion by more
    than twice the noise on calls or on any contact, and loses by no more than that on the other."""
    if champion is None:
        return True, "no champion yet"
    gains = {
        k: (challenger[f"qini_{k}"] - champion[f"qini_{k}"], 2 * challenger[f"noise_{k}"])
        for k in ("call", "any_contact")
        if f"qini_{k}" in challenger and f"qini_{k}" in champion
    }
    if not gains:
        return False, "no comparable metrics: champion kept"
    if any(gain < -margin for gain, margin in gains.values()):
        return False, "worse than the champion beyond noise: champion kept"
    if any(gain > margin for gain, margin in gains.values()):
        return True, "better than the champion beyond noise"
    return False, "within noise of the champion: champion kept"


def _qini_ties(
    score: np.ndarray, treated: np.ndarray, outcome: np.ndarray, rng: np.random.Generator
) -> float:
    """Qini of a score with ties (the legacy 0/1 targeting), averaged over random tie-breaks."""
    return float(
        np.mean(
            [qini_coefficient(score + 1e-9 * rng.random(len(score)), treated, outcome) for _ in range(20)]
        )
    )


def run(
    conn: duckdb.DuckDBPyConnection,
    *,
    cutoff: datetime,
    out: Path,
    seed: int = 0,
    force: bool = False,
    pooled: bool = False,
) -> dict[str, Any]:
    """Load, train, write the challenger next to `out`, judge it against the champion at `out` on
    the same test rows, and replace the champion only if `promote` says so (or `force`). Params,
    metrics, the decision and the model go to MLflow (MLFLOW_TRACKING_URI; sqlite:///mlflow.db when unset)."""
    import mlflow

    rows = load_rows(conn)
    model, metrics = train(rows, cutoff=cutoff, seed=seed, pooled=pooled)
    out.parent.mkdir(parents=True, exist_ok=True)
    challenger = out.with_name(f"{out.stem}_challenger{out.suffix}")
    challenger.write_bytes(pickle.dumps(model))
    champion = (
        evaluate(pickle.loads(out.read_bytes()), rows, cutoff=cutoff, seed=seed) if out.exists() else None
    )
    promoted, why = (True, "forced (--promote)") if force else promote(metrics, champion)
    if promoted:
        out.write_bytes(challenger.read_bytes())
    mlflow.set_experiment("kept-uplift")
    with mlflow.start_run(run_name=model.model_version):
        mlflow.log_params({**model.params, "cutoff": cutoff.isoformat(), "features": len(model_inputs())})
        mlflow.log_metrics(metrics)
        if champion:
            mlflow.log_metrics({f"champion_{k}": v for k, v in champion.items()})
        mlflow.set_tags({"promoted": str(promoted), "decision": why})
        mlflow.log_artifact(str(challenger))
    return {"model_version": model.model_version, **metrics, "promoted": promoted, "decision": why}
