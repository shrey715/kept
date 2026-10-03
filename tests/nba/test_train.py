"""kept.nba.train on synthetic decisions: calls help customers who answer, the time split holds,
and a serving-style row (None / bool / enum string) scores like a training row."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from kept.contracts.feature_registry import model_inputs
from kept.nba.train import ACTIONS, train

pytestmark = pytest.mark.track_d


def _rows(n: int = 6_000, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({f: np.nan for f in model_inputs()}, index=range(n))
    df["answer_rate"] = rng.uniform(0, 1, n)
    df["pay_frequency"] = rng.choice(["weekly", "monthly", None], n)
    df["promise_intent"] = pd.Series(rng.choice([True, False, None], n), dtype=object)
    action = rng.choice([a.value for a in ACTIONS], n)
    base = 0.3 + 0.4 * (action != "wait") * (df.answer_rate > 0.5)  # contact helps only those who answer
    return df.assign(
        decision_id=[f"D-{i}" for i in range(n)],
        case_id=[f"CS-{i}" for i in range(n)],
        decision_at=[datetime(2026, 1, 1) + timedelta(hours=i) for i in range(n)],
        action=action,
        paid_14d=rng.uniform(0, 1, n) < base,
    )


def test_train_learns_uplift_and_splits_on_time() -> None:
    pytest.importorskip("lightgbm")
    rows = _rows()
    cutoff = rows.decision_at.iloc[4_200]
    model, m = train(rows, cutoff=cutoff)
    assert (m["rows_train"], m["rows_test"]) == (4_200, 1_800)
    assert all(m[f"qini_{a.value}"] > 0 for a in ACTIONS[1:])
    # a FeatureVector-style row: object columns with None, bools, an enum string
    serving = pd.DataFrame(
        [
            {
                **{f: None for f in model_inputs()},
                "answer_rate": 0.9,
                "pay_frequency": "weekly",
                "promise_intent": True,
            }
        ]
    )
    hi = model.uplift(serving)["call"].iloc[0]
    lo = model.uplift(serving.assign(answer_rate=0.1))["call"].iloc[0]
    assert hi - lo > 0.2
