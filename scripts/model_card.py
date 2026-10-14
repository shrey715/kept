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
        "importance": importance,
        "cutoff": UPLIFT_CUTOFF.date().isoformat(),
    }


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
