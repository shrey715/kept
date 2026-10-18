# ruff: noqa: E501  (docstrings)
"""`kept train`: fit the T-learner on randomly assigned decisions, check it on later ones.

Rows: features_train.training_rows (paid_14d_known only) joined to features_train.case_features at
as_of = decision_at - 1 second. Build both with
`dbt build --select path:models/features --vars '{training_spine: true}'`.
Time split: fit on decisions before `cutoff`, then on decisions from `cutoff` on: Qini per action vs
WAIT, plus "any contact vs WAIT". `noise_*` is the standard deviation of Qini under random rankings,
reported for continuity: it is not the promotion margin (see `promote`).

The gate (`run`): champion and challenger are each fitted at `seeds` seeds and scored as the mean over them
(one seed moves the call Qini by +-0.002, docs/reports/uplift_improvement.md). The margin is the case-bootstrap
SD of the paired champion-minus-challenger difference (`compare`). The challenger is also checked on the clean
outcome (account-sourced payments, covered cases) with the doubly robust Qini (`dr_compare`), and both are
valued against what the bank did (`policy_report`). The legacy strategy's recommendation field is no longer
scored: it is a look-ahead field.
"""

from __future__ import annotations

import pickle
import time
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from kept.contracts.enums import Action
from kept.contracts.feature_registry import model_inputs
from kept.nba.causal import CLIP, Nuisance, case_bootstrap, dr_qini, gate_qini, policy_value
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


# What the bank knew before deciding (dbt context_features.sql): registry inputs of the next challenger.
# The live champion was fitted without them and selects its own columns (the study calls them "context").
CONTEXT_COLS = [
    "pending_ptp", "ptp_due_in_days", "n_out_7d", "n_out_30d", "n_rpc_30d",
    "days_since_contact", "last_rpc", "last_ptp_made", "paid_prev7", "weekday",
]  # fmt: skip


def base_inputs() -> list[str]:
    """The registry's model inputs without CONTEXT_COLS: what the live champion, the best-hour model and the
    studies' "17 inputs" baseline are built on."""
    return [n for n in model_inputs() if n not in CONTEXT_COLS]


def load_rows(
    conn: duckdb.DuckDBPyConnection, *, source: str = "training_rows", extras: bool = False
) -> pd.DataFrame:
    """The model rows: every registry input a second before the decision (`model_inputs()`, the context inputs
    included). extras=True (offline studies) adds the account-sourced outcomes (paid_clean_14d, paid_amt_14d,
    covered) and cured_30d. With extras every row is kept and `covered` says whether its "no" can be trusted;
    "training_weeks" is the one-row-per-case-landmark table."""
    cols = ", ".join(f"f.{n}" for n in model_inputs())
    more = ""
    if extras:
        more = """, t.paid_clean_14d, t.paid_amt_14d, t.covered, t.paid_14d_known,
               coalesce(c.cure_flag and c.cure_date <= cast(t.label_at as date) + 30, false) as cured_30d,
               c.primary_product, t.crm_customer_id"""
    where = "where t.paid_14d_known" if not extras else ""
    return conn.sql(f"""
        select t.decision_id, t.case_id, t.decision_at, t.action, t.paid_14d,
               c.nba_recommendation_last, {cols}{more}
        from features_train.{source} t
        join features_train.case_features f
            on f.case_id = t.case_id and f.as_of = t.decision_at - interval 1 second
        join silver.collections_cases c on c.case_id = t.case_id
        {where}
        order by t.decision_at, t.decision_id""").df()


SEEDS = 3  # the gate averages the champion and the challenger over this many seeds
BOOT = 200  # case-bootstrap resamples for the paired difference
SD_MARGIN = 2.0  # the challenger must beat the champion by more than this many bootstrap SDs


def fit_model(
    rows: pd.DataFrame,
    cutoff: datetime,
    *,
    seed: int = 0,
    pooled: bool = False,
    like: TLearnerUplift | None = None,
) -> TLearnerUplift:
    """A T-learner fitted on `rows` before `cutoff`. `like`: the champion's recipe (arms, params, input columns) at
    another seed instead of the registry's current inputs."""
    rows = pool_nudges(rows) if pooled else rows
    early = (rows.decision_at < cutoff).to_numpy()
    if like is not None:
        X = rows[like._columns]
        params = {k: v for k, v in like.params.items() if k != "random_state"}
        learner = TLearnerUplift(like.actions, params=params, seed=seed)
    else:
        X = rows[list(model_inputs())]
        learner = TLearnerUplift(POOLED if pooled else ACTIONS, seed=seed)
    return learner.fit(
        X[early],
        action=rows.action[early],
        paid_14d=rows.paid_14d[early],
        is_random_assignment=pd.Series(True, index=rows.index[early]),
    )


def train(
    rows: pd.DataFrame, *, cutoff: datetime, seed: int = 0, pooled: bool = False
) -> tuple[TLearnerUplift, dict[str, float]]:
    """Fit on rows before cutoff; metrics on rows from cutoff (see the module docstring), one seed.
    pooled: one arm for email, push and SMS (`pool_nudges`)."""
    model = fit_model(rows, cutoff, seed=seed, pooled=pooled)
    return model, evaluate(model, rows, cutoff=cutoff, seed=seed)


def evaluate(
    model: TLearnerUplift, rows: pd.DataFrame, *, cutoff: datetime, seed: int = 0
) -> dict[str, float]:
    """The test-split metrics for any fitted model, so a champion and a challenger are judged on the
    same rows (decisions from cutoff on)."""
    rng = np.random.default_rng(seed)
    pooled = Action.PUSH not in model.actions
    rows = pool_nudges(rows) if pooled else rows
    early = (rows.decision_at < cutoff).to_numpy()
    late = rows[~early]
    lift = model.uplift(late)
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
        metrics[f"qini_{name}"] = qini_coefficient(score.to_numpy()[both], t, yy)
        metrics[f"noise_{name}"] = float(
            np.std([qini_coefficient(rng.random(len(t)), t, yy) for _ in range(100)])
        )
    metrics["paid_rate_test"] = float(np.mean(late.paid_14d)) if len(late) else float("nan")
    return metrics


def _scores(model: TLearnerUplift, frame: pd.DataFrame) -> dict[str, np.ndarray]:
    """The two rankings the gate judges: the call uplift, and the best contact uplift ("any contact")."""
    lift = model.uplift(frame)
    contacts = [a.value for a in model.actions if a is not Action.WAIT]
    return {"call": lift["call"].to_numpy(), "any_contact": lift[contacts].max(axis=1).to_numpy()}


def _paired(
    champs: Sequence[TLearnerUplift],
    challs: Sequence[TLearnerUplift],
    frame: pd.DataFrame,
    arms: Sequence[str],
    stat: Callable[[np.ndarray, str, np.ndarray], float],
    *,
    reps: int,
    seed: int,
) -> dict[str, dict[str, float]]:
    """For each arm ("call", "any_contact"): `stat(score, arm, weights)` averaged over the seeds for the champion and the
    challenger on `frame`, their difference (challenger minus champion) and the case-bootstrap SD of that difference."""
    sc = {n: [_scores(m, frame) for m in ms] for n, ms in (("champion", champs), ("challenger", challs))}
    out: dict[str, dict[str, float]] = {}
    for k in arms:

        def both(w: np.ndarray, k: str = k) -> np.ndarray:
            v = {n: float(np.mean([stat(s[k], k, w) for s in sc[n]])) for n in sc}
            return np.array([v["challenger"] - v["champion"], v["champion"], v["challenger"]])

        d, boot = both(np.ones(len(frame))), case_bootstrap(frame.case_id, both, reps=reps, seed=seed)
        out[k] = {"champion": float(d[1]), "challenger": float(d[2]), "diff": float(d[0]), "sd": float(boot[:, 0].std())}
    return out


def compare(
    champs: Sequence[TLearnerUplift],
    challs: Sequence[TLearnerUplift],
    rows: pd.DataFrame,
    *,
    cutoff: datetime,
    reps: int = BOOT,
    seed: int = 0,
) -> dict[str, dict[str, float]]:
    """The gate's Qini (treated against untreated directly), mean over the seeds, for the champion and the
    challenger on the decisions from `cutoff`, and the case-bootstrap SD of their paired difference, for calls and
    for any contact."""
    late = rows[(rows.decision_at >= cutoff).to_numpy()].reset_index(drop=True)
    late = pool_nudges(late) if Action.PUSH not in champs[0].actions else late
    wait = (late.action == Action.WAIT.value).to_numpy()
    y = late.paid_14d.to_numpy(float)
    treated = {"call": (late.action == Action.CALL.value).to_numpy(), "any_contact": ~wait}
    masks = {k: t | wait for k, t in treated.items()}

    def stat(score: np.ndarray, k: str, w: np.ndarray) -> float:
        m = masks[k]
        return gate_qini(score[m], treated[k][m].astype(float), y[m], w[m])

    return _paired(champs, challs, late, list(masks), stat, reps=reps, seed=seed)


def dr_compare(
    champs: Sequence[TLearnerUplift],
    challs: Sequence[TLearnerUplift],
    rows: pd.DataFrame,
    *,
    cutoff: datetime,
    reps: int = BOOT,
    seed: int = 0,
) -> dict[str, dict[str, float]]:
    """The same comparison on the clean outcome (paid_clean_14d on covered cases, the account-sourced payments) with the
    doubly robust Qini: outcome and propensity models are fitted on the decisions before `cutoff` (not on any candidate)
    and give each later decision a pseudo-outcome; rows whose propensity is outside CLIP are dropped (overlap). `rows` is
    the extras frame (`load_rows(extras=True)`)."""
    d = rows[rows.covered.to_numpy(bool)]
    d = d.assign(y=d.paid_clean_14d.astype(float))
    fit, ev = d[d.decision_at < cutoff], d[d.decision_at >= cutoff]
    cols = list(model_inputs())
    out: dict[str, dict[str, float]] = {}
    for k, arm in (("call", "call"), ("any_contact", "any")):
        f = fit if k == "call" else fit.assign(action=np.where(fit.action == "wait", "wait", "any"))
        e = ev if k == "call" else ev.assign(action=np.where(ev.action == "wait", "wait", "any"))
        n = Nuisance(cols, arm, "y", seed=seed).fit(f)
        mask, o = n.pseudo(e)
        ok = ((o.e >= CLIP[0]) & (o.e <= CLIP[1])).to_numpy()
        frame = ev[mask][ok].reset_index(drop=True)
        phi = o.phi.to_numpy()[ok]
        res = _paired(champs, challs, frame, [k], lambda score, _k, w, phi=phi: dr_qini(score, phi, w), reps=reps, seed=seed)
        out[k] = {**res[k], "rows": float(len(frame)), "overlap": float(ok.mean())}
    return out


def policy_report(
    model: TLearnerUplift, rows: pd.DataFrame, *, cutoff: datetime, reps: int = BOOT, seed: int = 0
) -> dict[str, float]:
    """The model's choice of action (its best P(paid) of every action, WAIT included) on the decisions from `cutoff`, valued
    doubly robustly on the clean outcome against what the bank did on the same rows (`causal.policy_value`: outcome models
    per action and a multinomial propensity, cross-fitted by case, rows where the bank's chance of the model's action is in
    CLIP). Per 1,000 decisions, with a 95% case-bootstrap interval. `rows` is the extras frame."""
    d = rows[rows.covered.to_numpy(bool)].reset_index(drop=True)
    late = (d.decision_at >= cutoff).to_numpy()
    pi = np.full(len(d), Action.WAIT.value, dtype=object)
    pi[late] = model.predict_proba(d[late]).idxmax(axis=1).to_numpy()
    v = policy_value(d.assign(y=d.paid_clean_14d.astype(float)), list(model_inputs()), pi, "y", evaluate=late, seed=seed)
    ok = ((v.e_pi >= CLIP[0]) & (v.e_pi <= CLIP[1])).to_numpy()
    t = d.loc[v.index[ok]]
    psi, y = v.psi.to_numpy()[ok], v.y.to_numpy()[ok]
    boot = case_bootstrap(t.case_id, lambda w: 1000 * (w * (psi - y)).sum() / w.sum(), reps=reps, seed=seed)
    return {
        "decisions": float(len(v)),
        "rows_kept": float(ok.sum()),
        "bank_value": float(y.mean()),
        "model_value": float(psi.mean()),
        "gap_per_1000": float(1000 * (psi - y).mean()),
        "gap_per_1000_lo": float(np.percentile(boot, 2.5)),
        "gap_per_1000_hi": float(np.percentile(boot, 97.5)),
        "share_changed": float((pi[v.index[ok]] != v.a.to_numpy()[ok]).mean()),
    }


def promote(
    challenger: dict[str, float],
    champion: dict[str, float] | None,
    paired: dict[str, dict[str, float]] | None = None,
    dr: dict[str, dict[str, float]] | None = None,
) -> tuple[bool, str]:
    """Champion/challenger gate (#83). `paired` (from `compare`) gives, for calls and any contact, the challenger-minus-
    champion Qini and the case-bootstrap SD of that difference: the challenger goes live only if it beats the champion by
    more than SD_MARGIN of those SDs on calls or on any contact, loses to it by no more than that on the other, and is not
    worse than it by more than that on the clean-outcome DR Qini (`dr`, from `dr_compare`) for either. Without `paired`
    (metrics only, no scores to bootstrap) the margin falls back to twice the random-ranking noise."""
    if champion is None:
        return True, "no champion yet"
    if paired is None:
        paired = {
            k: {"diff": challenger[f"qini_{k}"] - champion[f"qini_{k}"], "sd": challenger[f"noise_{k}"]}
            for k in ("call", "any_contact")
            if f"qini_{k}" in challenger and f"qini_{k}" in champion
        }
    if not paired:
        return False, "no comparable metrics: champion kept"
    if any(v["diff"] < -SD_MARGIN * v["sd"] for v in paired.values()):
        return False, "worse than the champion beyond noise: champion kept"
    if dr and any(v["diff"] < -SD_MARGIN * v["sd"] for v in dr.values()):
        return False, "worse than the champion beyond noise on the clean-outcome DR Qini: champion kept"
    if any(v["diff"] > SD_MARGIN * v["sd"] for v in paired.values()):
        return True, "better than the champion beyond noise"
    return False, "within noise of the champion: champion kept"


def run(
    conn: duckdb.DuckDBPyConnection,
    *,
    cutoff: datetime,
    out: Path,
    seed: int = 0,
    force: bool = False,
    pooled: bool = False,
    champion: Path | None = None,
    seeds: int = SEEDS,
    policy: bool = True,
) -> dict[str, Any]:
    """Load, train the challenger at `seeds` seeds, judge it against the champion (`champion`, default `out`; refitted at
    the same seeds with its own recipe) on the same test rows (`promote`), write the challenger next to `out` and replace
    `out` only if `promote` says so (or `force`). Params, metrics, the decision and the model go to MLflow
    (MLFLOW_TRACKING_URI; sqlite:///mlflow.db when unset). Stage timings are in the result's "seconds"."""
    import mlflow

    clock, seconds = time.perf_counter(), {}

    def lap(name: str) -> None:
        nonlocal clock
        seconds[name], clock = round(time.perf_counter() - clock, 1), time.perf_counter()

    extras = load_rows(conn, extras=True)
    rows = extras[extras.paid_14d_known.to_numpy(bool)].reset_index(drop=True)
    lap("load")
    models = [fit_model(rows, cutoff, seed=seed + i, pooled=pooled) for i in range(seeds)]
    model = models[0]
    metrics = evaluate(model, rows, cutoff=cutoff, seed=seed)
    out.parent.mkdir(parents=True, exist_ok=True)
    challenger = out.with_name(f"{out.stem}_challenger{out.suffix}")
    challenger.write_bytes(pickle.dumps(model))
    lap("fit_challenger")
    held = champion or out
    live: TLearnerUplift | None = pickle.loads(held.read_bytes()) if held.exists() else None
    champ_metrics = evaluate(live, rows, cutoff=cutoff, seed=seed) if live else None
    paired = dr = None
    result_extra: dict[str, Any] = {}
    if live:
        own = live.params.get("random_state")
        champs = [
            live if own == seed + i else fit_model(rows, cutoff, seed=seed + i, pooled=pooled, like=live)
            for i in range(seeds)
        ]
        lap("fit_champion")
        paired = compare(champs, models, rows, cutoff=cutoff, seed=seed)
        lap("gate_bootstrap")
        dr = dr_compare(champs, models, extras, cutoff=cutoff, seed=seed)
        lap("dr_qini")
        result_extra = {"paired": paired, "dr": dr}
        metrics = {**metrics, **{f"seedmean_qini_{k}": v["challenger"] for k, v in paired.items()}}
        champ_metrics = {**(champ_metrics or {}), **{f"seedmean_qini_{k}": v["champion"] for k, v in paired.items()}}
    if policy:
        result_extra["policy"] = {"challenger": policy_report(model, extras, cutoff=cutoff, seed=seed)}
        if live:
            result_extra["policy"]["champion"] = policy_report(live, extras, cutoff=cutoff, seed=seed)
        lap("policy_value")
    promoted, why = (True, "forced (--promote)") if force else promote(metrics, champ_metrics, paired, dr)
    if promoted and challenger != held:
        out.write_bytes(challenger.read_bytes())
    mlflow.set_experiment("kept-uplift")
    with mlflow.start_run(run_name=model.model_version):
        mlflow.log_params({**model.params, "cutoff": cutoff.isoformat(), "features": len(model_inputs()), "seeds": seeds})
        mlflow.log_metrics(metrics)
        if champ_metrics:
            mlflow.log_metrics({f"champion_{k}": v for k, v in champ_metrics.items()})
        for k, v in (paired or {}).items():
            mlflow.log_metrics({f"paired_{k}_{m}": x for m, x in v.items()})
        for k, v in (dr or {}).items():
            mlflow.log_metrics({f"dr_{k}_{m}": x for m, x in v.items()})
        mlflow.log_metrics({f"seconds_{k}": v for k, v in seconds.items()})
        mlflow.set_tags({"promoted": str(promoted), "decision": why})
        mlflow.log_artifact(str(challenger))
    return {
        "model_version": model.model_version, **metrics, **result_extra, "seconds": seconds,
        "promoted": promoted, "decision": why,
    }  # fmt: skip
