# ruff: noqa: E501  (report prose)
"""Decision B10 (docs/reports/decisions.md): uplift against a "who will pay" response model, and the learner choice.

    uv run --extra model --extra analysis python scripts/decision_B10.py [--warehouse data/warehouse/kept.duckdb]

Candidates are fitted as the live model is (rows with a known 14-day payment, the old label) and judged on the windows
of uplift_learners.py: variants chosen on validation (fitted before 15 Jul, scored 15 Jul to 15 Aug), then scored once on
the decisions from 15 Aug. The judge is the doubly robust (AIPW) Qini from nuisance models no candidate uses, on covered
cases. Two outcomes: the clean one (paid_clean_14d, account-sourced payments; primary) and the old label (paid_14d, which
counts link and app payments seen only as flags on the contact row; the upper bound, uplift_improvement.md).
Writes data/exports/reports/decision_B10.json and docs/reports/figures/dec_B10.png.
"""

from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier, LGBMRegressor
from uplift_learners import ARMS, COLS, CUTOFF, NUIS, VALID_FROM, dr_qini

from kept.nba.train import ACTIONS, load_rows
from kept.nba.uplift import DEFAULT_PARAMS, TLearnerUplift, _frame

REPO = Path(__file__).resolve().parents[1]
OUTCOMES = {"clean": "paid_clean_14d", "old_label": "paid_14d"}  # judge outcomes, on the same covered rows
TOPS, SURE = (0.1, 0.3, 0.5), 0.3
S_VARIANTS = {"S-learner": {}, "S-learner, larger trees": dict(n_estimators=200, num_leaves=15)}
CF_VARIANTS = {"Causal forest": {}, "Causal forest, larger leaves": dict(min_samples_leaf=200)}
LIVE = "T-learner (live settings)"
CHAMP = "Champion (live)"


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
        out = {"wait": np.zeros(len(X))} | {a: cf.effect(X).ravel() for a, cf in self.tau.items()}
        return pd.DataFrame(out, index=features.index)


def _arm(X: pd.DataFrame, a: Any) -> pd.DataFrame:
    """X with the action as a categorical input `_a` (one action for every row, or a Series of actions)."""
    return X.assign(_a=pd.Categorical([a] * len(X) if isinstance(a, str) else a, categories=[x.value for x in ACTIONS]))


def nuisance(train: pd.DataFrame, outcome: str) -> tuple[Any, Any]:
    out = LGBMClassifier(**NUIS).fit(_arm(_frame(train[COLS]), train.action.to_numpy()), train[outcome].astype(int))
    prop = LGBMClassifier(**NUIS).fit(_frame(train[COLS]), train.action)
    return out, prop


def pseudo(ev: pd.DataFrame, out: Any, prop: Any, act: str, outcome: str) -> tuple[Any, ...]:
    """(rows in this arm or waiting, AIPW pseudo-outcomes, the outcome model's m1 and m0)."""
    m = ev.action.isin([act, "wait"]).to_numpy()
    e = ev[m]
    Xe = _frame(e[COLS])
    m1, m0 = (out.predict_proba(_arm(Xe, x))[:, 1] for x in (act, "wait"))
    P = pd.DataFrame(prop.predict_proba(Xe), columns=prop.classes_)
    ps = np.clip(P[act].to_numpy() / (P[act].to_numpy() + P["wait"].to_numpy()), 0.05, 0.95)
    t, y = (e.action == act).to_numpy(float), e[outcome].to_numpy(float)
    return m, m1 - m0 + t / ps * (y - m1) - (1 - t) / (1 - ps) * (y - m0), m1, m0


def measure(models: dict[str, Any], ev: pd.DataFrame, out: Any, prop: Any, outcome: str) -> tuple[dict[str, Any], dict[str, list[Any]]]:
    """Per arm and in total: the doubly robust Qini (raw and in noise units); extra payers per 1,000 contacts in the
    top 10/30/50% (the mean pseudo-outcome there); and contacts on "sure things": the share of the top 30% whose
    estimated uplift is <= 0, with their mean chance of paying if left alone. The estimated uplift and that chance
    come from the judge's outcome model (m1 - m0 and m0), which no candidate uses. "Random" is the exact expectation
    of a random ranking (top k% = everyone, Qini 0). Totals pool the arms: Qini in noise units summed, the rest
    weighted by rows. Also returns, per name, each arm's (phi, uplift, m0, top sets) for the bootstrap."""
    rng = np.random.default_rng(0)
    res: dict[str, Any] = {}
    parts: dict[str, list[Any]] = {}
    for act in ARMS:
        m, phi, m1, m0 = pseudo(ev, out, prop, act, outcome)
        ref, n = m1 - m0, len(phi)
        noise = float(np.std([dr_qini(rng.random(n), phi) for _ in range(100)]))
        scores = {"Random": None} | {k: mdl.uplift(ev[m])[act].to_numpy() for k, mdl in models.items()}
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
    d: dict[str, list[float]] = {"a": [], "b": [], "diff": []}
    for _ in range(reps):
        w = [rng.poisson(1.0, len(p[0])).astype(float) for p in parts[a]]
        va, vb = (summarise(parts[x], w)["per_1000_top30"] for x in (a, b))
        d["a"].append(va), d["b"].append(vb), d["diff"].append(va - vb)
    return {k: [float(x) for x in np.percentile(v, [2.5, 97.5])] for k, v in d.items()}


def main() -> None:
    from reportlib import BLUE, KEPT, MUTED, plt, save, style, tidy

    ap = argparse.ArgumentParser()
    ap.add_argument("--warehouse", default=str(REPO / "data" / "warehouse" / "kept.duckdb"))
    args = ap.parse_args()
    conn = duckdb.connect(args.warehouse, read_only=True)
    conn.execute("set memory_limit = '4GB'; set threads = 4")
    rows = load_rows(conn, extras=True)
    known = rows[rows.paid_14d_known].assign(paid_14d=lambda d: d.paid_14d.astype(int))  # the live model's rows
    cov = known[known.covered].assign(paid_clean_14d=lambda d: d.paid_clean_14d.astype(int))  # the judge's rows

    def live(df: pd.DataFrame) -> TLearnerUplift:
        return TLearnerUplift(ACTIONS).fit(df[COLS], action=df.action, paid_14d=df.paid_14d, is_random_assignment=pd.Series(True, index=df.index))

    def judge(ev: pd.DataFrame, fit: pd.DataFrame, models: dict[str, Any]) -> dict[str, Any]:
        r = {}
        for key, col in OUTCOMES.items():
            out, prop = nuisance(fit, col)
            r[key] = measure(models, ev, out, prop, col)
        return r

    tune = known[known.decision_at < CUTOFF]
    fit, val = tune[tune.decision_at < VALID_FROM], tune[tune.decision_at >= VALID_FROM]
    cfit, cval = (cov[(cov.decision_at < VALID_FROM)], cov[(cov.decision_at >= VALID_FROM) & (cov.decision_at < CUTOFF)])
    cands: dict[str, Any] = {LIVE: live(fit), "Response model": ResponseModel().fit(fit)}
    cands |= {n: SLearner(p).fit(fit) for n, p in S_VARIANTS.items()} | {n: CausalForest(p).fit(fit) for n, p in CF_VARIANTS.items()}
    v = judge(cval, cfit, cands)
    vc = v["clean"][0]
    s_best, cf_best = (max(vs, key=lambda n: vc["total"]["models"][n]["qini_noise_units"]) for vs in (S_VARIANTS, CF_VARIANTS))
    print("validation done", s_best, cf_best, flush=True)
    full = known[known.decision_at < CUTOFF]
    cfull, ctest = cov[cov.decision_at < CUTOFF], cov[cov.decision_at >= CUTOFF]
    final: dict[str, Any] = {LIVE: live(full), CHAMP: pickle.loads((REPO / "data" / "exports" / "models" / "uplift.pkl").read_bytes()),
                             "Response model": ResponseModel().fit(full), s_best: SLearner(S_VARIANTS[s_best]).fit(full), cf_best: CausalForest(CF_VARIANTS[cf_best]).fit(full)}
    t = judge(ctest, cfull, final)
    res = {"windows": {"validation": "fitted before 15 Jul 2026, scored 15 Jul to 15 Aug", "test": "fitted before 15 Aug 2026, scored from 15 Aug"},
           "judged_on": "covered cases; clean = paid_clean_14d (account-sourced), old_label = paid_14d (contact flags included); candidates fitted on the live rows and label",
           "rows": {"fit_validation": len(fit), "validation": len(val), "fit_test": len(full), "test": int((known.decision_at >= CUTOFF).sum()),
                    "judge_fit_validation": len(cfit), "judge_validation": len(cval), "judge_fit_test": len(cfull), "judge_test": len(ctest)},
           "chosen_on_validation": {"s_learner": s_best, "causal_forest": cf_best},
           "validation": {k: v[k][0] for k in OUTCOMES}, "test": {k: t[k][0] for k in OUTCOMES},
           "paired_bootstrap_top30_live_vs_response": {k: paired_boot(t[k][1], LIVE, "Response model") for k in OUTCOMES}}
    (REPO / "data" / "exports" / "reports" / "decision_B10.json").write_text(json.dumps(res, indent=1))
    style()
    names = list(t["clean"][0]["total"]["models"])
    fig, axs = plt.subplots(1, 2, figsize=(9.5, 3.4), sharey=True)
    for ax, key, title in ((axs[0], "clean", "Clean outcome (primary)"), (axs[1], "old_label", "Old label (upper bound)")):
        T = t[key][0]["total"]["models"]
        y = list(range(len(names)))[::-1]
        vals = [T[n]["per_1000_top30"] for n in names]
        ax.barh(y, vals, color=[KEPT if n in (LIVE, CHAMP) else MUTED if n == "Random" else BLUE for n in names], height=0.6)
        for yi, val_ in zip(y, vals, strict=True):
            ax.text(val_, yi, f" {val_:+.1f}", va="center", fontsize=8)
        ax.set_yticks(y, names)
        ax.set_title(f"{title}: extra payers per 1,000, top 30%", loc="left", fontsize=8)
        tidy(ax)
    fig.suptitle(f"Covered test decisions from 15 Aug ({len(ctest):,}), call, SMS and email arms pooled; doubly robust", fontsize=8, color=MUTED, x=0.01, ha="left")
    print(save(fig, "dec_B10"))
    print(json.dumps({"chosen": res["chosen_on_validation"], "boot": res["paired_bootstrap_top30_live_vs_response"],
                      "test": {k: {n: {m: round(x, 3) for m, x in r.items()} for n, r in res["test"][k]["total"]["models"].items()} for k in OUTCOMES}}, indent=1))


if __name__ == "__main__":
    main()
