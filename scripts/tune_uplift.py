"""Hyperparameter search for the uplift model, behind the champion/challenger gate.

    uv run python scripts/tune_uplift.py [--trials 16] [--warehouse data/warehouse/scratch_copy.duckdb]

Honest by construction: candidates are compared on a validation window inside the training period (decisions
from VALID_FROM to the cutoff); the test decisions after the cutoff are touched once, by the best candidate,
through the same `evaluate` and `promote` the nightly uses. The tuned model is written as uplift_tuned.pkl;
it replaces nothing (the champion changes only through `kept train` and its gate).
Writes docs/reports/tuning.md.
"""

from __future__ import annotations

import argparse
import json
import pickle
import random
import time
from datetime import datetime
from pathlib import Path

import duckdb

from kept.contracts.feature_registry import model_inputs
from kept.nba.train import ACTIONS, evaluate, load_rows, promote
from kept.nba.uplift import DEFAULT_PARAMS, TLearnerUplift

REPO = Path(__file__).resolve().parents[1]
MODELS = REPO / "data" / "exports" / "models"
CUTOFF = datetime(2026, 8, 15)  # kept train's default: test = decisions from here on
VALID_FROM = datetime(2026, 7, 15)  # tuning compares candidates on 15 Jul to 15 Aug, before the test window
SPACE = {
    "num_leaves": [7, 15, 31, 63],
    "min_child_samples": [100, 200, 300, 600],
    "learning_rate": [0.02, 0.05, 0.1],
    "n_estimators": [100, 200, 400],
    "reg_lambda": [0.0, 1.0, 5.0, 20.0],
    "colsample_bytree": [0.6, 0.8, 1.0],
}


def fit(rows, params: dict, until: datetime, seed: int = 0) -> TLearnerUplift:  # type: ignore[no-untyped-def]
    early = (rows.decision_at < until).to_numpy()
    X = rows[list(model_inputs())]
    return TLearnerUplift(ACTIONS, params=params, seed=seed).fit(
        X[early],
        action=rows.action[early],
        paid_14d=rows.paid_14d[early],
        is_random_assignment=rows.action[early].map(lambda _: True),  # as kept.nba.train.train does
    )


def score(m: dict[str, float]) -> float:
    """What a candidate is ranked by: the gate's two arms, any contact and calls, in noise units."""
    return sum(
        m.get(f"qini_{k}", 0.0) / max(m.get(f"noise_{k}", 1e-9), 1e-9) for k in ("any_contact", "call")
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=16)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--warehouse", default=str(REPO / "data" / "warehouse" / "scratch_copy.duckdb"))
    args = ap.parse_args()
    rng = random.Random(args.seed)
    rows = load_rows(duckdb.connect(args.warehouse, read_only=True))
    tune = rows[rows.decision_at < CUTOFF]  # the test window stays out of tuning
    trials = [dict(DEFAULT_PARAMS)] + [
        {**DEFAULT_PARAMS, **{k: rng.choice(v) for k, v in SPACE.items()}} for _ in range(args.trials - 1)
    ]
    results = []
    for i, params in enumerate(trials):
        t0 = time.time()
        m = evaluate(fit(tune, params, VALID_FROM, args.seed), tune, cutoff=VALID_FROM, seed=args.seed)
        results.append((score(m), params, m))
        print(
            f"trial {i:2d} score {score(m):6.2f}  qini call {m.get('qini_call', 0):.4f}"
            f" any {m.get('qini_any_contact', 0):.4f}  {time.time() - t0:.0f}s",
            flush=True,
        )
    results.sort(key=lambda r: -r[0])
    best_score, best, _ = results[0]
    tuned = fit(rows, best, CUTOFF, args.seed)  # refit on everything before the cutoff
    challenger = evaluate(tuned, rows, cutoff=CUTOFF, seed=args.seed)
    champion = evaluate(
        pickle.loads((MODELS / "uplift.pkl").read_bytes()), rows, cutoff=CUTOFF, seed=args.seed
    )
    promoted, why = promote(challenger, champion)
    (MODELS / "uplift_tuned.pkl").write_bytes(pickle.dumps(tuned))
    keys = ("qini_call", "noise_call", "qini_any_contact", "noise_any_contact")
    lines = [
        "# Uplift model: hyperparameter search",
        "",
        f"{len(trials)} candidates (the defaults plus {len(trials) - 1} random draws), compared on decisions"
        f" from {VALID_FROM:%d %b} to {CUTOFF:%d %b} (inside the training period); the best was refit on"
        f" everything before {CUTOFF:%d %b} and judged once on the test decisions after it, by the nightly's"
        " own gate.",
        "",
        "    uv run python scripts/tune_uplift.py",
        "",
        "## On the test decisions",
        "",
        "| Model | Qini, calls | noise | Qini, any contact | noise |",
        "|---|---:|---:|---:|---:|",
        "| Champion (live) | " + " | ".join(f"{champion.get(k, 0):.4f}" for k in keys) + " |",
        "| Tuned challenger | " + " | ".join(f"{challenger.get(k, 0):.4f}" for k in keys) + " |",
        "",
        f"**Gate: {why}.** "
        + (
            "The tuned model can go live through `kept train`'s promotion."
            if promoted
            else "The champion stays; the search is on record so nobody has to rerun it."
        ),
        "",
        "## Best settings (validation window)",
        "",
        "```json",
        json.dumps({k: best[k] for k in SPACE}, indent=1),
        "```",
        "",
        "## Every candidate (validation score: Qini over noise, calls plus any contact)",
        "",
        "| # | score | " + " | ".join(SPACE) + " |",
        "|---:|---:|" + "---:|" * len(SPACE),
        *[
            f"| {i + 1} | {s:.2f} | " + " | ".join(str(p[k]) for k in SPACE) + " |"
            for i, (s, p, _) in enumerate(results)
        ],
    ]
    (REPO / "docs" / "reports" / "tuning.md").write_text("\n".join(lines) + "\n")
    print(f"best validation score {best_score:.2f}; test gate: {why}")


if __name__ == "__main__":
    main()
