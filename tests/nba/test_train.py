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
    assert m["qini_call"] > 2 * m["noise_call"] and not any(k.startswith("qini_legacy") for k in m)  # look-ahead: gone
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


def _paired(call: float, any_: float, sd: float = 0.001) -> dict[str, dict[str, float]]:
    return {"call": {"diff": call, "sd": sd}, "any_contact": {"diff": any_, "sd": sd}}


def test_gate_margin_is_the_bootstrap_sd_of_the_paired_difference() -> None:
    from kept.nba.train import promote

    champ = {"qini_call": 0.01, "qini_any_contact": 0.005}
    assert promote({}, champ, _paired(0.0035, 0.0)) == (True, "better than the champion beyond noise")  # 3.5 sd on calls
    assert promote({}, champ, _paired(0.0, 0.0035))[0] is True  # or on any contact
    assert promote({}, champ, _paired(0.0015, -0.001))[0] is False  # within 2 sd (the old margin was the random-ranking noise)
    assert promote({}, champ, _paired(0.0035, -0.0035)) == (False, "worse than the champion beyond noise: champion kept")
    assert promote({}, champ, _paired(-0.01, -0.01))[0] is False  # a clear loss
    # a wider bootstrap SD (noisier comparison) raises the bar for the same gain
    assert promote({}, champ, _paired(0.0035, 0.0, sd=0.002))[0] is False


def test_gate_blocks_a_challenger_worse_on_the_clean_outcome() -> None:
    from kept.nba.train import promote

    champ = {"qini_call": 0.01, "qini_any_contact": 0.005}
    win = _paired(0.005, 0.0)
    assert promote({}, champ, win, {"call": {"diff": 0.0, "sd": 0.001}, "any_contact": {"diff": -0.001, "sd": 0.001}})[0]
    why = promote({}, champ, win, {"call": {"diff": -0.003, "sd": 0.001}, "any_contact": {"diff": 0.0, "sd": 0.001}})
    assert why == (False, "worse than the champion beyond noise on the clean-outcome DR Qini: champion kept")


def test_paired_comparison_and_the_dr_check_on_synthetic_rows() -> None:
    """A model with the signal beats one fitted on shuffled outcomes, beyond 2 bootstrap SDs, on the gate Qini and on the
    clean-outcome DR Qini; the same model against itself differs by exactly nothing."""
    pytest.importorskip("lightgbm")
    from kept.nba.train import compare, dr_compare, fit_model, policy_report, promote

    rows = _rows()
    rows = rows.assign(paid_clean_14d=rows.paid_14d, covered=True, paid_14d_known=True)
    cutoff = rows.decision_at.iloc[4_200]
    good = [fit_model(rows, cutoff, seed=s) for s in (0, 1)]
    bad_rows = rows.assign(paid_14d=np.random.default_rng(1).permutation(rows.paid_14d.to_numpy()))
    bad = [fit_model(bad_rows, cutoff, seed=s) for s in (0, 1)]
    same = compare(good, good, rows, cutoff=cutoff, reps=30)
    assert same["call"]["diff"] == 0 and same["call"]["sd"] == 0
    cmp_ = compare(bad, good, rows, cutoff=cutoff, reps=30)
    assert cmp_["call"]["diff"] > 2 * cmp_["call"]["sd"] > 0 and cmp_["call"]["challenger"] > cmp_["call"]["champion"]
    dr = dr_compare(bad, good, rows, cutoff=cutoff, reps=30)
    assert dr["call"]["diff"] > 0 and dr["call"]["overlap"] > 0.5
    assert promote({}, {"x": 0.0}, cmp_, dr)[0] is True and promote({}, {"x": 0.0}, compare(good, bad, rows, cutoff=cutoff, reps=30))[0] is False
    pol = policy_report(good[0], rows, cutoff=cutoff, reps=30)
    assert {"gap_per_1000", "gap_per_1000_lo", "gap_per_1000_hi", "share_changed"} <= set(pol)


def test_champion_recipe_is_refitted_at_another_seed_with_its_own_columns() -> None:
    pytest.importorskip("lightgbm")
    from kept.nba.train import fit_model

    rows = _rows()
    champion = fit_model(rows, rows.decision_at.iloc[4_200], seed=0)
    champion._columns = champion._columns[:5]  # an older model with fewer inputs
    again = fit_model(rows, rows.decision_at.iloc[4_200], seed=2, like=champion)
    assert again._columns == champion._columns and again.params["random_state"] == 2
    assert again.params["num_leaves"] == champion.params["num_leaves"]


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
