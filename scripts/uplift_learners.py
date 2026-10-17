# ruff: noqa: E501, B023  (report prose; loop variables in bootstrap lambdas are used before the next iteration)
"""Uplift learners against the live T-learner, judged two ways: docs/reports/uplift_learners.md.

    uv run python scripts/uplift_learners.py [--warehouse data/warehouse/scratch_copy.duckdb]

The gate's Qini (kept.nba.train.evaluate) compares treated and untreated decisions directly; the bank chose who got
which action, so that comparison is biased. The doubly robust Qini sorts decisions by a candidate's uplift and adds up
AIPW pseudo-outcomes from nuisance models that no candidate uses (one outcome model with the action as an input, one
propensity model). Candidates are compared on a validation window (15 Jul to 15 Aug, fitted before it); the chosen one
is then scored once on the test decisions (from 15 Aug), next to the champion and the bank's strategy.
"""

from __future__ import annotations

import argparse
import json
import pickle
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier, LGBMRegressor

from kept.contracts.enums import Action
from kept.contracts.feature_registry import model_inputs
from kept.nba.causal import CLIP, CausalUplift, Nuisance, case_bootstrap, gate_qini
from kept.nba.causal import dr_qini as dr_qini_w
from kept.nba.legacy import legacy_to_action
from kept.nba.train import ACTIONS, CONTEXT_COLS, evaluate, load_rows
from kept.nba.uplift import TLearnerUplift, _frame

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "docs" / "reports" / "uplift_learners.md"
CUTOFF, VALID_FROM = datetime(2026, 8, 15), datetime(2026, 7, 15)
COLS = list(model_inputs())
ARMS = ("call", "sms_payment_link", "email")
NUIS = dict(n_estimators=300, num_leaves=31, min_child_samples=300, learning_rate=0.05, verbose=-1, deterministic=True, force_row_wise=True)
REG = dict(n_estimators=300, num_leaves=15, min_child_samples=300, learning_rate=0.03, reg_lambda=5.0, colsample_bytree=0.8, verbose=-1, deterministic=True, force_row_wise=True)
VARIANTS = {"DR-learner": {}, "DR-learner, more regularised": dict(num_leaves=7, min_child_samples=1000, reg_lambda=20.0)}


class MetaLearner:
    """X- or DR-learner per contact arm against waiting, on the T-learner's outcome models. Same surface the gate uses."""

    def __init__(self, kind: str, reg: dict[str, Any]) -> None:
        self.kind, self.reg, self.actions, self.tau = kind, {**REG, **reg}, ACTIONS, {}

    def fit(self, df: pd.DataFrame) -> MetaLearner:
        X, a, y = _frame(df[COLS]), df.action.to_numpy(), df.paid_14d.to_numpy(dtype=float)
        mu = TLearnerUplift(ACTIONS).fit(df[COLS], action=df.action, paid_14d=df.paid_14d, is_random_assignment=pd.Series(True, index=df.index))
        P = mu.predict_proba(df[COLS])
        for act in ACTIONS:
            if act is Action.WAIT:
                continue
            m = (a == act.value) | (a == "wait")
            Xm, ym, t = X[m], y[m], (a[m] == act.value).astype(int)
            e = LGBMClassifier(n_estimators=200, num_leaves=15, min_child_samples=300, learning_rate=0.05, verbose=-1).fit(Xm, t)
            ps = np.clip(e.predict_proba(Xm)[:, 1], 0.05, 0.95)
            m1, m0 = P[act.value].to_numpy()[m], P["wait"].to_numpy()[m]
            if self.kind == "dr":
                phi = m1 - m0 + t / ps * (ym - m1) - (1 - t) / (1 - ps) * (ym - m0)
                self.tau[act] = (LGBMRegressor(**self.reg).fit(Xm, phi), None, None)
            else:
                r1 = LGBMRegressor(**self.reg).fit(Xm[t == 1], ym[t == 1] - m0[t == 1])
                r0 = LGBMRegressor(**self.reg).fit(Xm[t == 0], m1[t == 0] - ym[t == 0])
                self.tau[act] = (r1, r0, e)
        return self

    def uplift(self, features: pd.DataFrame) -> pd.DataFrame:
        X, out = _frame(features[COLS]), {"wait": np.zeros(len(features))}
        for act, (f1, f0, e) in self.tau.items():
            if f0 is None:
                out[act.value] = f1.predict(X)
            else:
                g = np.clip(e.predict_proba(X)[:, 1], 0.05, 0.95)
                out[act.value] = g * f0.predict(X) + (1 - g) * f1.predict(X)
        return pd.DataFrame(out, index=features.index)[[a.value for a in ACTIONS]]


def nuisance(train: pd.DataFrame) -> tuple[Any, Any]:
    cats = [a.value for a in ACTIONS]
    out = LGBMClassifier(**NUIS).fit(_frame(train[COLS]).assign(_a=pd.Categorical(train.action, categories=cats)), train.paid_14d.astype(int))
    prop = LGBMClassifier(**NUIS).fit(_frame(train[COLS]), train.action)
    return out, prop


def pseudo(ev: pd.DataFrame, out: Any, prop: Any, act: str) -> tuple[np.ndarray, np.ndarray]:
    cats = [a.value for a in ACTIONS]
    m = ev.action.isin([act, "wait"]).to_numpy()
    e = ev[m]
    Xe = _frame(e[COLS])
    m1, m0 = (out.predict_proba(Xe.assign(_a=pd.Categorical([x] * len(Xe), categories=cats)))[:, 1] for x in (act, "wait"))
    P = pd.DataFrame(prop.predict_proba(Xe), columns=prop.classes_)
    ps = np.clip(P[act].to_numpy() / (P[act].to_numpy() + P["wait"].to_numpy()), 0.05, 0.95)
    t, y = (e.action == act).to_numpy(float), e.paid_14d.to_numpy(float)
    return m, m1 - m0 + t / ps * (y - m1) - (1 - t) / (1 - ps) * (y - m0)


def dr_qini(score: np.ndarray, phi: np.ndarray) -> float:
    """Area between the doubly robust gain curve and the straight line to its end (> 0: better than random)."""
    o = np.argsort(-score, kind="stable")
    g = np.concatenate([[0.0], np.cumsum(phi[o])]) / len(phi)
    return float(np.trapezoid(g, np.arange(len(phi) + 1) / len(phi)) - 0.5 * g[-1])


def judge(models: dict[str, Any], ev: pd.DataFrame, out: Any, prop: Any) -> dict[str, dict[str, float]]:
    rng = np.random.default_rng(0)
    legacy = ev.nba_recommendation_last.map(lambda c: (a := legacy_to_action(c)) and a.value)
    res: dict[str, dict[str, float]] = {}
    for act in ARMS:
        m, phi = pseudo(ev, out, prop, act)
        row = {"noise": float(np.std([dr_qini(rng.random(len(phi)), phi) for _ in range(100)]))}
        row["The bank's strategy"] = dr_qini((legacy[m] == act).to_numpy(float) + 1e-9 * rng.random(m.sum()), phi)
        for name, mdl in models.items():
            row[name] = dr_qini(mdl.uplift(ev[m])[act].to_numpy(), phi)
        res[act] = row
    return res


def table(res: dict[str, dict[str, float]]) -> str:
    names = [k for k in next(iter(res.values())) if k != "noise"]
    lines = ["| Arm | Noise (1 sd) | " + " | ".join(names) + " |", "|---|---:|" + "---:|" * len(names)]
    for act, row in res.items():
        lines.append(f"| {act.replace('_', ' ')} | {row['noise']:.4f} | " + " | ".join(f"{row[n]:+.4f}" for n in names) + " |")
    return "\n".join(lines)


# ---------------------------------------------------------------- --improve: docs/reports/uplift_improvement.md
IMPROVE_JSON = REPO / "data" / "exports" / "reports" / "uplift_improve.json"
F17, F27 = COLS, COLS + CONTEXT_COLS
SEEDS = (0, 1, 2)
# training sets: name -> (rows, outcome column, binary). Evaluation sets are the same three, scored with nuisance fitted on their own fit window.
SETS = {
    "old rows (attempts, any payment)": ("att", "paid_14d"),
    "attempts, clean payment (covered)": ("att", "paid_clean_14d"),
    "landmarks, clean payment (covered)": ("lm", "paid_clean_14d"),
}
PRIMARY = "attempts, clean payment (covered)"


def subset(frames: dict[str, pd.DataFrame], name: str) -> pd.DataFrame:
    kind, outcome = SETS[name]
    d = frames[kind]
    d = d[d.paid_14d_known] if outcome == "paid_14d" else d[d.covered]
    return d.assign(y=d[outcome].astype(float)).reset_index(drop=True)


def candidates(fit: dict[str, pd.DataFrame], seed: int) -> dict[str, Any]:
    """Every candidate fitted on `fit` (a frame per training set). Name: learner | training set."""
    out: dict[str, Any] = {}
    for sname in SETS:
        d = fit[sname]
        ones = pd.Series(True, index=d.index)
        for fname, cols in (("17 inputs", F17), ("17 + context", F27)):
            out[f"T-learner, {fname} | {sname}"] = TLearnerUplift(ACTIONS, seed=seed).fit(d[cols], action=d.action, paid_14d=d.y, is_random_assignment=ones)
        cu = CausalUplift(F27, ["call", "sms_payment_link", "email", "push"], "y", seed=seed).fit(d)
        out[f"DR-learner, 17 + context | {sname}"] = cu.view("dr")
        out[f"R-learner, 17 + context | {sname}"] = cu.view("r")
    return out


def eval_sets(fit: dict[str, pd.DataFrame], ev: dict[str, pd.DataFrame]) -> dict[str, dict[str, Any]]:
    """Pseudo-outcomes per evaluation set and arm from nuisance fitted on the fit window (not any candidate), rows trimmed to overlap."""
    res: dict[str, dict[str, Any]] = {}
    for sname in SETS:
        res[sname] = {}
        for arm in ARMS:
            n = Nuisance(F27, arm, "y").fit(fit[sname])
            m, o = n.pseudo(ev[sname])
            e = ev[sname][m]
            ok = ((o.e >= CLIP[0]) & (o.e <= CLIP[1])).to_numpy()
            res[sname][arm] = {"rows": e[ok], "phi": o.phi.to_numpy()[ok], "kept": float(ok.mean())}
    return res


def score_all(models: dict[int, dict[str, Any]], es: dict[str, dict[str, Any]], reps: int = 100) -> dict[str, Any]:
    """DR Qini per candidate, evaluation set and arm: mean over seeds, and the case-bootstrap SD of its difference from the champion."""
    champion = next(n for n in models[SEEDS[0]] if n.startswith("T-learner, 17 inputs | old rows"))
    out: dict[str, Any] = {}
    for sname, arms in es.items():
        for arm, e in arms.items():
            rows, phi = e["rows"], e["phi"]
            sc = {n: [models[s][n].uplift(rows[F27])[arm].to_numpy() for s in SEEDS] for n in models[SEEDS[0]]}
            stat = lambda w, n: float(np.mean([dr_qini_w(x, phi, w) for x in sc[n]]))  # noqa: E731
            base = case_bootstrap(rows.case_id, lambda w: stat(w, champion), reps=reps)
            for n in sc:
                v = stat(np.ones(len(phi)), n)
                diff = case_bootstrap(rows.case_id, lambda w, n=n: stat(w, n) - stat(w, champion), reps=reps) if n != champion else np.zeros(2)
                out.setdefault(n, {}).setdefault(sname, {})[arm] = {"qini": v, "vs_champion": v - stat(np.ones(len(phi)), champion), "diff_sd": float(diff.std()), "seed_min": float(min(dr_qini_w(x, phi) for x in sc[n])), "seed_max": float(max(dr_qini_w(x, phi) for x in sc[n])), "kept": e["kept"]}
            out[champion][sname][arm]["boot_sd"] = float(base.std())
    return out


def gate(models: dict[int, dict[str, Any]], test: pd.DataFrame) -> dict[str, dict[str, float]]:
    """The gate's own metric (treated vs untreated directly; old rows, any payment) for every candidate, mean over seeds, and its
    noise as the gate defines it (SD of Qini under random rankings)."""
    d = test[test.paid_14d_known]
    wait = (d.action == "wait").to_numpy()
    y = d.paid_14d.to_numpy(float)
    rng = np.random.default_rng(0)
    out: dict[str, dict[str, float]] = {}
    for n in models[SEEDS[0]]:
        per: dict[str, list[float]] = {"call": [], "any_contact": []}
        for s in SEEDS:
            lift = models[s][n].uplift(d[F27])
            for k in per:
                arm = (d.action == "call").to_numpy() if k == "call" else ~wait
                both = arm | wait
                score = lift["call"] if k == "call" else lift[[c for c in lift.columns if c != "wait"]].max(axis=1)
                per[k].append(gate_qini(score.to_numpy()[both], arm[both].astype(float), y[both]))
        out[n] = {f"qini_{k}": float(np.mean(v)) for k, v in per.items()} | {f"seed_sd_{k}": float(np.std(v)) for k, v in per.items()}
    for k in ("call", "any_contact"):
        arm = (d.action == "call").to_numpy() if k == "call" else ~wait
        both = arm | wait
        noise = float(np.std([gate_qini(rng.random(both.sum()), arm[both].astype(float), y[both]) for _ in range(50)]))
        for n in out:
            out[n][f"noise_{k}"] = noise
    return out


def improve(conn: duckdb.DuckDBPyConnection) -> None:
    frames = {"att": load_rows(conn, extras=True), "lm": load_rows(conn, source="training_weeks", extras=True)}
    for f in frames.values():
        f["last_rpc"], f["last_ptp_made"] = f.last_rpc.astype(float), f.last_ptp_made.astype(float)
    res: dict[str, Any] = {}
    for stage, hi in {"validation": VALID_FROM, "test": CUTOFF}.items():
        fit = {n: subset(frames, n)[lambda d: d.decision_at < hi] for n in SETS}
        ev_from, ev_to = (VALID_FROM, CUTOFF) if stage == "validation" else (CUTOFF, datetime(2026, 10, 1))
        ev = {n: subset(frames, n)[lambda d: (d.decision_at >= ev_from) & (d.decision_at < ev_to)] for n in SETS}
        fit_win = {n: d for n, d in fit.items()}
        models = {s: candidates(fit_win, s) for s in SEEDS}
        es = eval_sets(fit_win, ev)
        att = frames["att"]
        res[stage] = {"dr": score_all(models, es), "gate": gate(models, att[(att.decision_at >= ev_from) & (att.decision_at < ev_to)]), "rows": {n: len(d) for n, d in ev.items()}, "fit_rows": {n: len(d) for n, d in fit.items()}}
        IMPROVE_JSON.write_text(json.dumps(res, indent=1, default=float))
        print(stage, "done", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--warehouse", default=str(REPO / "data" / "warehouse" / "scratch_copy.duckdb"))
    ap.add_argument("--improve", action="store_true", help="the uplift_improvement.md candidate comparison (needs features_train v2 rows)")
    args = ap.parse_args()
    if args.improve:
        conn = duckdb.connect(args.warehouse, read_only=True)
        conn.execute("set memory_limit = '4GB'; set threads = 4")
        improve(conn)
        return
    rows = load_rows(duckdb.connect(args.warehouse, read_only=True))
    tune = rows[rows.decision_at < CUTOFF]
    fit, val = tune[tune.decision_at < VALID_FROM], tune[tune.decision_at >= VALID_FROM]
    out, prop = nuisance(fit)
    cands: dict[str, Any] = {"T-learner (as live)": TLearnerUplift(ACTIONS).fit(fit[COLS], action=fit.action, paid_14d=fit.paid_14d, is_random_assignment=pd.Series(True, index=fit.index)),
                             "X-learner": MetaLearner("x", {}).fit(fit)}
    cands |= {n: MetaLearner("dr", v).fit(fit) for n, v in VARIANTS.items()}
    v = judge(cands, val, out, prop)
    best = max((n for n in cands if n != "T-learner (as live)"), key=lambda n: sum(v[a][n] / v[a]["noise"] for a in ARMS))
    full, test = rows[rows.decision_at < CUTOFF], rows[rows.decision_at >= CUTOFF]
    out, prop = nuisance(full)
    champion = pickle.loads((REPO / "data" / "exports" / "models" / "uplift.pkl").read_bytes())
    kind, reg = ("x", {}) if best == "X-learner" else ("dr", VARIANTS[best])
    chosen = MetaLearner(kind, reg).fit(full)
    t = judge({"Champion (live)": champion, best: chosen}, test, out, prop)
    gate = {n: evaluate(m, rows, cutoff=CUTOFF) for n, m in (("Champion (live)", champion), (best, chosen))}
    gate_md = "\n".join(
        ["| Model | Qini, calls | Qini, any contact | Noise (calls, any) |", "|---|---:|---:|---:|"]
        + [f"| {n} | {g['qini_call']:+.4f} | {g['qini_any_contact']:+.4f} | {g['noise_call']:.4f}, {g['noise_any_contact']:.4f} |" for n, g in gate.items()]
    )
    OUT.write_text(f"""# Uplift learners: does a causal learner beat the live model?

Generated by `scripts/uplift_learners.py`. Uplift is the extra chance of a payment within 14 days from an action
against waiting. The bank chose the actions, so two ways of scoring a ranking are shown: the doubly robust Qini (AIPW
pseudo-outcomes from nuisance models no candidate uses; it corrects for who the bank chose to contact) and the gate's
Qini (treated against untreated directly, as `kept train` promotes on). Noise is the standard deviation of the score
under random rankings.

## Validation (fitted before 15 Jul, scored 15 Jul to 15 Aug)

{table(v)}

Chosen for the test by the sum over arms in noise units: **{best}**.

## Test, scored once (fitted before 15 Aug, scored on the {len(test):,} decisions after)

{table(t)}

The gate's own metric on the same test decisions:

{gate_md}

## What it shows

- **No learner beats the live model on every arm.** The causal learner wins on some arms and loses on others, and the
  arms that win on validation don't all win on the test. The gate keeps the live model, correctly.
- **On SMS and email, both Kept models beat the bank's strategy** on the doubly robust score. **On calls, the bank's
  targeting scores higher** on that measure while the gate's measure says the opposite: who gets a call is the arm
  most shaped by the bank's own choices, and the two scores disagree there.
- The bank's randomised cells say contact intensity barely changes outcomes (`evidence.md` §1), so a small uplift
  signal is the expected result. Kept's main lever is the due date (`evidence.md` §2, §2a).
""")
    (REPO / "data" / "exports" / "reports" / "uplift_learners.json").write_text(
        json.dumps({"best": best, "test": t, "gate": {n: {k: g[k] for k in ("qini_call", "qini_any_contact")} for n, g in gate.items()}}, indent=1)
    )
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
