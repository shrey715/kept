# ruff: noqa: E501  (report prose)
"""Uplift learners against the live T-learner, judged two ways: docs/reports/uplift_learners.md.

    uv run python scripts/uplift_learners.py [--warehouse data/warehouse/scratch_copy.duckdb]

The gate's Qini (kept.nba.train.evaluate) compares treated and untreated decisions directly; the bank chose who got
which action, so that comparison is biased. The doubly robust Qini sorts decisions by a candidate's uplift and adds up
AIPW pseudo-outcomes from nuisance models that no candidate uses (one outcome model with the action as an input, one
propensity model). Candidates are compared on a validation window (15 Jul to 15 Aug, fitted before it); the chosen one
is then scored once on the test decisions (from 15 Aug), next to the champion and the bank's strategy.

    uv run --extra model --extra analysis python scripts/uplift_learners.py --mode decision   # decision B10

Decision B10 (docs/reports/decisions.md): the same windows and doubly robust Qini, for uplift against a "who will pay"
response model, an S-learner and a causal forest (econml, the `analysis` extra). Writes
data/exports/reports/decision_B10.json and docs/reports/figures/dec_B10.png.
"""

from __future__ import annotations

import argparse
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
from kept.nba.legacy import legacy_to_action
from kept.nba.train import ACTIONS, evaluate, load_rows
from kept.nba.uplift import DEFAULT_PARAMS, TLearnerUplift, _frame

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "docs" / "reports" / "uplift_learners.md"
CUTOFF, VALID_FROM = datetime(2026, 8, 15), datetime(2026, 7, 15)
COLS = list(model_inputs())
ARMS = ("call", "sms_payment_link", "email")
NUIS = dict(n_jobs=4, n_estimators=300, num_leaves=31, min_child_samples=300, learning_rate=0.05, verbose=-1, deterministic=True, force_row_wise=True)
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


class ResponseModel:
    """What a propensity-to-pay score does: one LightGBM (the live tree settings) for paid_14d on contacted decisions.
    Every arm is ranked by that chance of paying, so `uplift` returns the same score in every column."""

    def fit(self, df: pd.DataFrame) -> ResponseModel:
        c = df[df.action != "wait"]
        self.m = LGBMClassifier(**DEFAULT_PARAMS, random_state=0).fit(_frame(c[COLS]), c.paid_14d.astype(int))
        return self

    def uplift(self, features: pd.DataFrame) -> pd.DataFrame:
        p = self.m.predict_proba(_frame(features[COLS]))[:, 1]
        return pd.DataFrame({a.value: p for a in ACTIONS}, index=features.index)


class SLearner:
    """One LightGBM with the action as an input; uplift = P(paid | x, action) - P(paid | x, wait)."""

    def __init__(self, params: dict[str, Any]) -> None:
        self.params = {**DEFAULT_PARAMS, **params, "random_state": 0}

    def fit(self, df: pd.DataFrame) -> SLearner:
        self.m = LGBMClassifier(**self.params).fit(_arm(_frame(df[COLS]), df.action.to_numpy()), df.paid_14d.astype(int))
        return self

    def uplift(self, features: pd.DataFrame) -> pd.DataFrame:
        X = _frame(features[COLS])
        p = {a.value: self.m.predict_proba(_arm(X, a.value))[:, 1] for a in ACTIONS}
        return pd.DataFrame(p, index=features.index).sub(p["wait"], axis=0)


class CausalForest:
    """econml's CausalForestDML per judged arm against waiting (a generalised random forest on the residualised outcome
    and treatment). econml's forest defaults apart from `params`. Its trees take no missing values, which LightGBM
    routes on its own, so a missing input takes the training median plus a 0/1 "was missing" column."""

    def __init__(self, params: dict[str, Any]) -> None:
        self.params, self.tau = params, {}

    def _num(self, df: pd.DataFrame) -> np.ndarray:
        X = _frame(df[COLS])
        X = X.assign(pay_frequency=X.pay_frequency.cat.codes.replace(-1, np.nan)).astype(float)
        return np.hstack([X.fillna(self.fill).to_numpy(), X[self.miss].isna().to_numpy(float)])

    def fit(self, df: pd.DataFrame) -> CausalForest:
        from econml.dml import CausalForestDML

        X = _frame(df[COLS]).drop(columns="pay_frequency").astype(float)
        self.fill = X.median().fillna(0.0).reindex(COLS, fill_value=0.0)  # pay_frequency codes: 0 when missing
        self.miss = [c for c in COLS if df[c].isna().any() and df[c].notna().any()]
        Xn, y = self._num(df), df.paid_14d.to_numpy(float)
        small = dict(n_jobs=4, n_estimators=200, num_leaves=15, min_child_samples=300, learning_rate=0.05, verbose=-1, random_state=0)
        for act in ARMS:
            m = df.action.isin([act, "wait"]).to_numpy()
            cf = CausalForestDML(model_y=LGBMRegressor(**small), model_t=LGBMClassifier(**small), discrete_treatment=True, inference=False, random_state=0, n_jobs=4, **self.params)
            self.tau[act] = cf.fit(y[m], (df.action[m] == act).to_numpy(int), X=Xn[m])
        return self

    def uplift(self, features: pd.DataFrame) -> pd.DataFrame:
        X = self._num(features)
        out ={"wait": np.zeros(len(X))} | {a: cf.effect(X).ravel() for a, cf in self.tau.items()}
        return pd.DataFrame(out, index=features.index)


def _arm(X: pd.DataFrame, a: Any) -> pd.DataFrame:
    """X with the action as a categorical input `_a` (one action for every row, or a Series of actions)."""
    return X.assign(_a=pd.Categorical([a] * len(X) if isinstance(a, str) else a, categories=[x.value for x in ACTIONS]))


def nuisance(train: pd.DataFrame) -> tuple[Any, Any]:
    out = LGBMClassifier(**NUIS).fit(_arm(_frame(train[COLS]), train.action.to_numpy()), train.paid_14d.astype(int))
    prop = LGBMClassifier(**NUIS).fit(_frame(train[COLS]), train.action)
    return out, prop


def pseudo(ev: pd.DataFrame, out: Any, prop: Any, act: str, *, means: bool = False) -> Any:
    """(rows in this arm or waiting, AIPW pseudo-outcomes); means=True also returns the outcome model's m1 and m0."""
    m = ev.action.isin([act, "wait"]).to_numpy()
    e = ev[m]
    Xe = _frame(e[COLS])
    m1, m0 = (out.predict_proba(_arm(Xe, x))[:, 1] for x in (act, "wait"))
    P = pd.DataFrame(prop.predict_proba(Xe), columns=prop.classes_)
    ps = np.clip(P[act].to_numpy() / (P[act].to_numpy() + P["wait"].to_numpy()), 0.05, 0.95)
    t, y = (e.action == act).to_numpy(float), e.paid_14d.to_numpy(float)
    phi = m1 - m0 + t / ps * (y - m1) - (1 - t) / (1 - ps) * (y - m0)
    return (m, phi, m1, m0) if means else (m, phi)


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


TOPS, SURE = (0.1, 0.3, 0.5), 0.3
S_VARIANTS = {"S-learner": {}, "S-learner, larger trees": dict(n_estimators=200, num_leaves=15)}
CF_VARIANTS = {"Causal forest": {}, "Causal forest, larger leaves": dict(min_samples_leaf=200)}
LIVE = "T-learner (live settings)"


def measure(models: dict[str, Any], ev: pd.DataFrame, out: Any, prop: Any) -> tuple[dict[str, Any], dict[str, list[Any]]]:
    """Per arm and in total: the doubly robust Qini (raw and in noise units); extra payers per 1,000 contacts in the
    top 10/30/50% (the mean pseudo-outcome there); and contacts on "sure things": the share of the top 30% whose
    estimated uplift is <= 0, with their mean chance of paying if left alone. The estimated uplift and that chance
    come from the judge's outcome model (m1 - m0 and m0), which no candidate uses. "Random" is the exact expectation
    of a random ranking (top k% = everyone, Qini 0). Totals pool the arms: Qini in noise units summed, the rest
    weighted by rows. Also returns, per name, each arm's (phi, uplift, m0, top sets) for the bootstrap."""
    rng = np.random.default_rng(0)
    legacy = ev.nba_recommendation_last.map(lambda c: (a := legacy_to_action(c)) and a.value)
    res: dict[str, Any] = {}
    parts: dict[str, list[Any]] = {}
    for act in ARMS:
        m, phi, m1, m0 = pseudo(ev, out, prop, act, means=True)
        ref, n = m1 - m0, len(phi)
        noise = float(np.std([dr_qini(rng.random(n), phi) for _ in range(100)]))
        scores = {"Random": None, "The bank's strategy": (legacy[m] == act).to_numpy(float) + 1e-9 * rng.random(n)}
        scores |= {k: mdl.uplift(ev[m])[act].to_numpy() for k, mdl in models.items()}
        res[act] = {"rows": n, "noise": noise, "models": {}}
        for name, s in scores.items():
            o = np.arange(n) if s is None else np.argsort(-s, kind="stable")
            top = {k: o if s is None else o[: round(k * n)] for k in TOPS}
            q = 0.0 if s is None else dr_qini(s, phi)
            parts.setdefault(name, []).append((phi, ref, m0, top))
            res[act]["models"][name] = {"qini": q, "qini_noise_units": q / noise} | summarise([(phi, ref, m0, top)])
    res["total"] = {"rows": sum(res[a]["rows"] for a in ARMS), "models": {
        n: {"qini_noise_units": sum(res[a]["models"][n]["qini_noise_units"] for a in ARMS)} | summarise(p) for n, p in parts.items()}}
    return res, parts


def summarise(parts: list[Any], w: list[np.ndarray] | None = None) -> dict[str, float]:
    """Pooled over arms (optionally with bootstrap weights): extra payers per 1,000 in each top set, and the sure-thing
    share and chance of paying if left alone in the top 30%."""
    z = list(zip(w or [np.ones(len(p[0])) for p in parts], parts, strict=True))

    def mean(k: float, val: Any) -> float:  # weighted mean of val(phi, ref, m0)[top k] over the pooled arms
        return float(sum((wi[p[3][k]] * val(*p[:3])[p[3][k]]).sum() for wi, p in z) / sum(wi[p[3][k]].sum() for wi, p in z))

    out = {f"per_1000_top{round(k * 100)}": 1000 * mean(k, lambda phi, ref, m0: phi) for k in TOPS}
    out["sure_things_top30"] = mean(SURE, lambda phi, ref, m0: (ref <= 0).astype(float))
    out["p_pay_if_left_top30"] = mean(SURE, lambda phi, ref, m0: m0)
    return out


def paired_boot(parts: dict[str, list[Any]], a: str, b: str, reps: int = 1000) -> dict[str, list[float]]:
    """95% interval of a minus b, extra payers per 1,000 in the top 30%, all arms: the decisions resampled (the same
    Poisson weights for both), the models and the judge held fixed."""
    rng = np.random.default_rng(0)
    d = {"a": [], "b": [], "diff": []}
    for _ in range(reps):
        w = [rng.poisson(1.0, len(p[0])).astype(float) for p in parts[a]]
        va, vb = (summarise(parts[x], w)["per_1000_top30"] for x in (a, b))
        d["a"].append(va), d["b"].append(vb), d["diff"].append(va - vb)
    return {k: [float(x) for x in np.percentile(v, [2.5, 97.5])] for k, v in d.items()}


def decision(rows: pd.DataFrame) -> None:
    import json

    from reportlib import BLUE, KEPT, MUTED, plt, save, style, tidy

    def live(df: pd.DataFrame) -> TLearnerUplift:
        return TLearnerUplift(ACTIONS).fit(df[COLS], action=df.action, paid_14d=df.paid_14d, is_random_assignment=pd.Series(True, index=df.index))

    tune = rows[rows.decision_at < CUTOFF]
    fit, val = tune[tune.decision_at < VALID_FROM], tune[tune.decision_at >= VALID_FROM]
    out, prop = nuisance(fit)
    cands: dict[str, Any] = {LIVE: live(fit), "Response model": ResponseModel().fit(fit)}
    cands |= {n: SLearner(p).fit(fit) for n, p in S_VARIANTS.items()} | {n: CausalForest(p).fit(fit) for n, p in CF_VARIANTS.items()}
    v, _ = measure(cands, val, out, prop)
    s_best, cf_best = (max(vs, key=lambda n: v["total"]["models"][n]["qini_noise_units"]) for vs in (S_VARIANTS, CF_VARIANTS))
    full, test = rows[rows.decision_at < CUTOFF], rows[rows.decision_at >= CUTOFF]
    out, prop = nuisance(full)
    final: dict[str, Any] = {LIVE: live(full), "Champion (live)": pickle.loads((REPO / "data" / "exports" / "models" / "uplift.pkl").read_bytes()),
                             "Response model": ResponseModel().fit(full), s_best: SLearner(S_VARIANTS[s_best]).fit(full), cf_best: CausalForest(CF_VARIANTS[cf_best]).fit(full)}
    t, parts = measure(final, test, out, prop)
    res = {"windows": {"validation": "fitted before 15 Jul 2026, scored 15 Jul to 15 Aug", "test": "fitted before 15 Aug 2026, scored from 15 Aug"},
           "rows": {"fit_validation": len(fit), "validation": len(val), "fit_test": len(full), "test": len(test)},
           "chosen_on_validation": {"s_learner": s_best, "causal_forest": cf_best}, "validation": v, "test": t,
           "paired_bootstrap_top30_live_vs_response": paired_boot(parts, LIVE, "Response model")}
    (REPO / "data" / "exports" / "reports" / "decision_B10.json").write_text(json.dumps(res, indent=1))
    style()
    T = t["total"]["models"]
    names = list(T)
    fig, axs = plt.subplots(1, 2, figsize=(9.5, 3.4), sharey=True)
    for ax, key, title, fmt in ((axs[0], "per_1000_top30", "Extra payers per 1,000 contacts, top 30%", "{:+.1f}"),
                                (axs[1], "sure_things_top30", "Share of the top 30% with estimated uplift ≤ 0", "{:.0%}")):
        y = list(range(len(names)))[::-1]
        vals = [T[n][key] for n in names]
        ax.barh(y, vals, color=[KEPT if n in (LIVE, "Champion (live)") else MUTED if n in ("Random", "The bank's strategy") else BLUE for n in names], height=0.6)
        for yi, val_ in zip(y, vals, strict=True):
            ax.text(val_, yi, " " + fmt.format(val_), va="center", fontsize=8)
        ax.set_yticks(y, names)
        ax.set_title(title, loc="left")
        tidy(ax)
    fig.suptitle(f"Test decisions from 15 Aug ({len(test):,}), call, SMS and email arms pooled; doubly robust", fontsize=8, color=MUTED, x=0.01, ha="left")
    print(save(fig, "dec_B10"))
    print(json.dumps({"chosen": res["chosen_on_validation"], "test_total": T, "boot": res["paired_bootstrap_top30_live_vs_response"]}, indent=1))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--warehouse", default=str(REPO / "data" / "warehouse" / "scratch_copy.duckdb"))
    ap.add_argument("--mode", choices=("learners", "decision"), default="learners", help="decision: B10, uplift against a response model")
    args = ap.parse_args()
    rows = load_rows(duckdb.connect(args.warehouse, read_only=True))
    if args.mode == "decision":
        return decision(rows)
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
    import json

    (REPO / "data" / "exports" / "reports" / "uplift_learners.json").write_text(
        json.dumps({"best": best, "test": t, "gate": {n: {k: g[k] for k in ("qini_call", "qini_any_contact")} for n, g in gate.items()}}, indent=1)
    )
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
