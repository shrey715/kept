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
        nba_recommendation_last=rng.choice(["call_evening", "sms_payment_link", None], n),  # untargeted
    )


def test_train_learns_uplift_and_splits_on_time() -> None:
    pytest.importorskip("lightgbm")
    rows = _rows()
    cutoff = rows.decision_at.iloc[4_200]
    model, m = train(rows, cutoff=cutoff)
    assert (m["rows_train"], m["rows_test"]) == (4_200, 1_800)
    assert all(m[f"qini_{a.value}"] > 0 for a in ACTIONS[1:])
    # the plan's check: the model targets better than the legacy strategy, beyond noise
    assert m["qini_call"] - m["qini_legacy_call"] > 2 * m["noise_call"]
    assert m["qini_any_contact"] > m["qini_legacy_any_contact"]
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


def test_champion_challenger_gate() -> None:
    """#83: promote only beyond noise on calls or any contact, never if either loses beyond noise."""
    from kept.nba.train import promote

    def m(call: float, anyc: float) -> dict[str, float]:
        return {"qini_call": call, "noise_call": 0.001, "qini_any_contact": anyc, "noise_any_contact": 0.001}

    champ = m(0.010, 0.005)
    assert promote(m(0.010, 0.005), None) == (True, "no champion yet")
    assert promote(m(0.0105, 0.0055), champ)[0] is False  # within noise
    assert promote(m(0.013, 0.005), champ)[0] is True  # calls better by 3 noise, any contact level
    assert promote(m(0.013, 0.002), champ)[0] is False  # any contact worse beyond noise


def test_pooled_nudge_arm() -> None:
    """#80: one arm for email, push and SMS; the engine scores push and SMS with it."""
    pytest.importorskip("lightgbm")
    from kept.contracts.enums import Action
    from kept.nba.engine import _scored_as
    from kept.nba.train import POOLED

    rows = _rows()
    model, m = train(rows, cutoff=rows.decision_at.iloc[4_200], pooled=True)
    assert model.actions == POOLED
    assert "qini_email" in m and "qini_push" not in m and m["qini_any_contact"] > 0
    scored = _scored_as(["wait", "email", "call"], protective=False)
    assert scored[Action.PUSH] is Action.EMAIL and scored[Action.SMS_PAYMENT_LINK] is Action.EMAIL
    assert (
        _scored_as(["wait", "email", "push", "sms_payment_link", "call"], protective=False)[Action.PUSH]
        is Action.PUSH
    )
