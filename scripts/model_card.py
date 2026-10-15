# ruff: noqa: E501  (report text)
"""The model card behind the Portfolio page's Models section, from the live models and their held-out rows.

    uv run python scripts/model_card.py [--warehouse data/warehouse/scratch_copy.duckdb]

Promise model (data/exports/models/promise.pkl): AUC, Brier, a 10-bin reliability curve, TreeSHAP importance
on promises made after its cutoff (never seen in training or calibration). Uplift model (uplift.pkl): the
any-contact Qini curve on decisions after its cutoff, against random targeting, and TreeSHAP importance per
action on a sample of those decisions. Writes data/exports/reports/model_card.json. Read-only on the warehouse
(the copy by default, so it runs next to kept serve).
"""

from __future__ import annotations

import argparse
import json
import pickle
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import numpy as np

from kept.contracts.feature_registry import model_inputs
from kept.nba import promise_model
from kept.nba.explain import DRIVER_LABELS
from kept.nba.train import load_rows
from kept.nba.uplift import qini_coefficient, qini_curve

REPO = Path(__file__).resolve().parents[1]
MODELS = REPO / "data" / "exports" / "models"
OUT = REPO / "data" / "exports" / "reports" / "model_card.json"
UPLIFT_CUTOFF = datetime(2026, 8, 15)  # kept train's default split
PROMISE_LABELS = {
    "days_to_due": "Days from promise to due date",
    "dpd": "Days past due when promised",
    "prior_broken_90d": "Broken promises, prior 90 days",
    "prior_kept_ratio": "Share of past promises kept",
    "days_after_pay": "Days from last payday to due date",
    "days_before_next_pay": "Days from due date to next payday",
}


def promise_card(conn: duckdb.DuckDBPyConnection) -> dict[str, object]:
    from sklearn.metrics import brier_score_loss, roc_auc_score  # type: ignore[import-untyped]

    model = promise_model.load_model(MODELS / "promise.pkl")
    if model is None:
        return {}
    rows = promise_model.load(conn)
    test = rows[rows.created >= promise_model.CUTOFF]
    p = model.p_kept(test.to_dict("records"))
    y = test.kept.to_numpy()
    bins = np.clip((p * 10).astype(int), 0, 9)
    reliability = [
        {
            "predicted": float(p[bins == b].mean()),
            "observed": float(y[bins == b].mean()),
            "n": int((bins == b).sum()),
        }
        for b in range(10)
        if (bins == b).sum() >= 50
    ]
    X = test[list(promise_model.FEATURES)].astype(float)
    contrib = np.asarray(model._model.predict_proba(X, pred_contrib=True))[:, :-1]  # TreeSHAP, log-odds
    share = np.abs(contrib).mean(axis=0)
    share = share / share.sum()
    importance = sorted(
        (
            {"feature": f, "label": PROMISE_LABELS.get(f, f), "share": float(s)}
            for f, s in zip(promise_model.FEATURES, share, strict=True)
        ),
        key=lambda d: -d["share"],
    )
    return {
        "rows_test": len(test),
        "auc": float(roc_auc_score(y, p)),
        "brier": float(brier_score_loss(y, p)),
        "kept_rate": float(y.mean()),
        "reliability": reliability,
        "importance": importance,
        "cutoff": promise_model.CUTOFF.date().isoformat(),
    }


NUDGES = ("sms_payment_link", "email", "push")


def arm_curves(late, lift, contacts, rng, steps: int = 41, draws: int = 30) -> dict[str, object]:  # type: ignore[no-untyped-def]
    """Per arm (calls, digital nudges, any contact) against waiting: extra payments as the share contacted grows,
    for the model's ranking, the bank's strategy (its recommendation, ties broken at random) and random order
    (the 5th-95th percentile band of 30 random rankings). Gains are payments, as in qini_curve."""
    from kept.contracts.enums import Action
    from kept.nba.engine import DEFAULT_CONTACT_COST
    from kept.nba.legacy import legacy_to_action

    legacy = late.nba_recommendation_last.map(lambda c: (x := legacy_to_action(c)) and x.value).to_numpy()
    wait = (late.action == "wait").to_numpy()
    y_all = late.paid_14d.to_numpy(dtype=int)
    out: dict[str, object] = {}
    for name, members in (("call", ("call",)), ("nudge", NUDGES), ("any", tuple(contacts))):
        members = tuple(m for m in members if m in contacts)
        if not members:
            continue
        arm = late.action.isin(members).to_numpy()
        both = arm | wait
        t, y = arm[both].astype(int), y_all[both]
        if not t.any() or t.all():
            continue
        model = lift[list(members)].max(axis=1).to_numpy()[both]
        bank = np.isin(legacy[both], members).astype(float) + 1e-9 * rng.random(both.sum())
        frac, g_model = qini_curve(model, t, y)
        _, g_bank = qini_curve(bank, t, y)
        pick = np.linspace(0, len(frac) - 1, steps).astype(int)
        rand = np.array([qini_curve(rng.random(len(t)), t, y)[1][pick] for _ in range(draws)])
        lo, hi = np.percentile(rand, [5, 95], axis=0)
        mix = late.action[arm].value_counts()
        cost = sum(float(DEFAULT_CONTACT_COST[Action(a)]) * n for a, n in mix.items()) / int(t.sum())
        recommended = np.isin(legacy[both], members)  # where the bank's strategy picks this arm
        out[name] = {
            "bank_recommended": int(recommended.sum()),
            # of those, the share the model expects to add under half a point of payment chance
            "bank_low_uplift_share": float((model[recommended] < 0.005).mean()) if recommended.any() else None,
            "decisions": int(both.sum()),
            "contacts": int(t.sum()),
            "cost_per_contact": round(cost, 4),  # the engine's contact costs, over this arm's actual mix
            "end": float(g_model[-1]),
            "qini": float(qini_coefficient(model, t, y)),
            "qini_bank": float(qini_coefficient(bank, t, y)),
            "curve": [
                {"frac": float(frac[i]), "model": float(g_model[i]), "bank": float(g_bank[i]), "lo": float(a), "hi": float(b)}
                for i, a, b in zip(pick, lo, hi, strict=True)
            ],
        }
    return out


def uplift_card(conn: duckdb.DuckDBPyConnection, *, sample: int = 4000, seed: int = 0) -> dict[str, object]:
    model = pickle.loads((MODELS / "uplift.pkl").read_bytes())
    rows = load_rows(conn)
    late = rows[rows.decision_at >= UPLIFT_CUTOFF]
    cols = list(model_inputs())
    lift = model.uplift(late[cols])
    contacts = [a.value for a in model.actions if a.value != "wait"]
    wait = (late.action == "wait").to_numpy()
    contact = late.action.isin(contacts).to_numpy()
    both = wait | contact
    score = lift[contacts].max(axis=1).to_numpy()[both]
    t, y = contact[both].astype(int), late.paid_14d.to_numpy(dtype=int)[both]
    frac, gain = qini_curve(score, t, y)
    pick = np.linspace(0, len(frac) - 1, 41).astype(int)  # 40 steps is plenty for a chart
    rng = np.random.default_rng(seed)
    arms = arm_curves(late, lift, contacts, rng)
    rows_s = late.sample(min(sample, len(late)), random_state=seed)
    importance = {}
    for a in [x for x in ("call", "sms_payment_link", "email") if x in contacts]:
        c = model.contributions_many(rows_s[cols], next(x for x in model.actions if x.value == a))
        mean = np.abs(c).mean(axis=0) * 100
        top = np.argsort(-mean)[:10]
        importance[a] = [
            {"feature": cols[i], "label": DRIVER_LABELS.get(cols[i], cols[i]), "pts": float(mean[i])}
            for i in top
        ]
    return {
        "rows_test": len(late),
        "qini_any_contact": float(qini_coefficient(score, t, y)),
        "qini_noise": float(np.std([qini_coefficient(rng.random(len(t)), t, y) for _ in range(30)])),
        "curve": [{"frac": float(frac[i]), "gain": float(gain[i])} for i in pick],
        "random_end": float(gain[-1]),
        "arms": arms,
        "importance": importance,
        "cutoff": UPLIFT_CUTOFF.date().isoformat(),
    }


def to_markdown(card: dict) -> str:  # type: ignore[type-arg]
    """The committed model card (docs/reports/model_card.md): the same numbers as the JSON the Portfolio page reads."""
    p, u = card["promise"], card["uplift"]
    lines = [
        "# Model card: the promise model and the uplift model",
        "",
        f"Written by `scripts/model_card.py` on {card['written'][:10]} from held-out data the models never saw "
        "(the JSON behind the Portfolio page's models panel is `data/exports/reports/model_card.json`).",
        "",
        "## Promise model: will this promise be kept?",
        "",
        "LightGBM on six point-in-time features, isotonic-calibrated; trained on promises due before "
        f"{p['cutoff']}, tested on the {p['rows_test']:,} due after.",
        "",
        "| Measure | Value |",
        "|---|---:|",
        f"| AUC | {p['auc']:.3f} |",
        f"| Brier score | {p['brier']:.3f} |",
        f"| Kept rate in the test window | {p['kept_rate']:.1%} |",
        "",
        "Alone it ranks promises less well than the bank's own score (AUC 0.702); combined with it, 0.728, a gain of 2.5 AUC points [1.9, 3.3] on the same promises "
        "(`docs/reports/evidence.md` §6). A first version scored 0.92 because one feature, `amount_ratio`, encoded the "
        "outcome; it was removed. Read as published, the bank's score overstates the kept rate by about 24 points; recalibrated, "
        "it is as well calibrated as ours, so calibration is not our edge: ours exists when the promise is made, about 9 days "
        "before the bank's score, and adds to it (`evidence.md` §7).",
        "",
        "**Calibration (predicted against observed, by score bin)**",
        "",
        "| Predicted | Observed | Promises |",
        "|---:|---:|---:|",
        *[f"| {r['predicted']:.1%} | {r['observed']:.1%} | {r['n']:,} |" for r in p["reliability"]],
        "",
        "**What drives it (share of mean |TreeSHAP|)**",
        "",
        "| Feature | Share |",
        "|---|---:|",
        *[f"| {r['label']} | {r['share']:.1%} |" for r in p["importance"]],
        "",
        "## Uplift model: which action changes the outcome?",
        "",
        "A LightGBM T-learner: one model per action against waiting, on paid-within-14-days; trained on decisions "
        f"before {u['cutoff']}, tested on the {u['rows_test']:,} after.",
        "",
        "| Measure | Value |",
        "|---|---:|",
        f"| Qini, any contact against waiting | {u['qini_any_contact']:.4f} |",
        f"| Spread of Qini over 30 random rankings | {u['qini_noise']:.4f} |",
        "",
        "The signal is small and the gate treats it that way: a challenger replaces the champion only if it beats it "
        "by more than the noise on held-out decisions (`docs/reports/tuning.md`: a 40-candidate search did not).",
        "",
        "**Strongest inputs per action (mean |TreeSHAP|, percentage points)**",
        "",
        "| Action | Inputs |",
        "|---|---|",
        *[
            f"| {a.replace('_', ' ')} | "
            + ", ".join(f"{r['label']} ({r['pts']:.1f})" for r in rows[:5])
            + " |"
            for a, rows in u["importance"].items()
        ],
        "",
        "## Limits",
        "",
        "- Actions were not randomised except across the bank's strategy cells, so uplift is estimated, not measured; "
        "the pilot's randomised due-date cell is how it gets measured.",
        "- Protected attributes are not model inputs; the fairness and invariance checks are in "
        "`docs/reports/fairness_report.pdf`.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--warehouse", default=str(REPO / "data" / "warehouse" / "scratch_copy.duckdb"))
    args = ap.parse_args()
    conn = duckdb.connect(args.warehouse, read_only=True)
    card = {
        "written": datetime.now(UTC).isoformat(timespec="seconds"),
        "promise": promise_card(conn),
        "uplift": uplift_card(conn),
    }
    OUT.write_text(json.dumps(card, indent=1))
    (REPO / "docs" / "reports" / "model_card.md").write_text(to_markdown(card))
    p, u = card["promise"], card["uplift"]
    print(
        f"promise AUC {p.get('auc', 0):.3f} Brier {p.get('brier', 0):.3f}"
        f" on {p.get('rows_test')} held-out promises"
    )
    print(
        f"uplift Qini (any contact) {u['qini_any_contact']:.4f} ± {u['qini_noise']:.4f}"
        f" on {u['rows_test']} decisions"
    )
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
