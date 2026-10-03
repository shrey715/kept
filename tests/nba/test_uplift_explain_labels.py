"""Stage 4 (uplift + Qini), stage 7 (explanations), and outcome labels."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from kept.contracts import Action, DpdBucket
from kept.contracts.feature_registry import model_inputs
from kept.nba.explain import REASON_TEMPLATES, similar_cases_text, top_reasons
from kept.nba.labels import paid_within, roll_forward_rate, rolled_forward
from kept.nba.uplift import TLearnerUplift, qini_coefficient, qini_curve

T0 = datetime(2026, 9, 28, 10, 0, tzinfo=UTC)


# ----------------------------------------------------------------- qini
def test_qini_curve_hand_computed() -> None:
    frac, gain = qini_curve(np.array([0.9, 0.8, 0.7, 0.6]), np.array([1, 0, 1, 0]), np.array([1, 0, 0, 0]))
    np.testing.assert_allclose(frac, [0, 0.25, 0.5, 0.75, 1.0])
    np.testing.assert_allclose(gain, [0, 1, 1, 1, 1])


def test_qini_sorts_by_score() -> None:
    a = qini_curve(np.array([0.6, 0.9, 0.7, 0.8]), np.array([0, 1, 1, 0]), np.array([0, 1, 0, 0]))
    b = qini_curve(np.array([0.9, 0.8, 0.7, 0.6]), np.array([1, 0, 1, 0]), np.array([1, 0, 0, 0]))
    np.testing.assert_allclose(a[1], b[1])


def _synthetic(n: int = 20_000, seed: int = 0) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    x = rng.uniform(-1, 1, n)
    t = rng.integers(0, 2, n)
    p = 0.2 + 0.3 * t * (x > 0)  # treatment only helps when x > 0
    y = (rng.random(n) < p).astype(int)
    return x, t, y


def test_qini_oracle_beats_random_beats_anti_oracle() -> None:
    x, t, y = _synthetic()
    rng = np.random.default_rng(1)
    oracle = qini_coefficient(x, t, y)
    random = qini_coefficient(rng.random(len(x)), t, y)
    anti = qini_coefficient(-x, t, y)
    assert oracle > 0.02
    assert abs(random) < 0.01
    assert anti < -0.02


@pytest.mark.parametrize(
    "t,y",
    [
        (np.array([0, 1, 2]), np.array([0, 1, 0])),
        (np.array([0, 1, 1]), np.array([0, 1, 5])),
        (np.array([0, 1]), np.array([0, 1, 0])),
    ],
)
def test_qini_validates_inputs(t: np.ndarray, y: np.ndarray) -> None:
    with pytest.raises(ValueError):
        qini_curve(np.array([0.1, 0.2, 0.3]), t, y)


# ----------------------------------------------------------------- T-learner
def test_t_learner_validation() -> None:
    m = TLearnerUplift(actions=(Action.WAIT, Action.CALL))
    X = pd.DataFrame({"max_dpd": [1, 2], "paid_14d": [0, 1]})
    with pytest.raises(ValueError):  # outcome leaked into features
        m.fit(
            X,
            action=pd.Series(["wait", "call"]),
            paid_14d=pd.Series([0, 1]),
            is_random_assignment=pd.Series([True, True]),
        )
    with pytest.raises(RuntimeError):
        TLearnerUplift().predict_proba(pd.DataFrame({"max_dpd": [1]}))


@pytest.mark.integration
@pytest.mark.slow
def test_t_learner_recovers_heterogeneous_effect_from_random_rows_only() -> None:
    pytest.importorskip("lightgbm")
    x, t, y = _synthetic(n=8_000)
    rng = np.random.default_rng(2)
    # non-random rows where calls always "work": must be ignored
    k = 2_000
    xn = rng.uniform(-1, 1, k)
    X = pd.DataFrame({"x": np.concatenate([x, xn])})
    action = pd.Series(np.where(np.concatenate([t, np.ones(k, int)]) == 1, "call", "wait"))
    paid = pd.Series(np.concatenate([y, np.ones(k, int)]))
    is_random = pd.Series([True] * len(x) + [False] * k)
    m = TLearnerUplift(actions=(Action.WAIT, Action.CALL), seed=0).fit(
        X, action=action, paid_14d=paid, is_random_assignment=is_random
    )
    grid = pd.DataFrame({"x": np.linspace(-0.95, 0.95, 40)})
    proba = m.predict_proba(grid)
    assert (
        list(proba.columns) == ["wait", "call"]
        and proba.to_numpy().min() >= 0
        and proba.to_numpy().max() <= 1
    )
    up = m.uplift(grid)
    assert (up["wait"] == 0).all()
    pos, neg = up["call"][grid.x > 0].mean(), up["call"][grid.x < 0].mean()
    assert pos - neg > 0.15
    assert abs(neg) < 0.1
    assert m.model_version


# ----------------------------------------------------------------- explanations
TEMPLATES = {
    "days_to_next_payroll": "Pay lands in {value} days; past promises fell due before payday and broke",
    "pay_change_vs_3m_avg": "Pay is down on the 3-month average",
    "answer_rate_after_18h": "Answers most calls after 18:00",
    "max_dpd": "Days past due is {value}",
}


def test_top_three_positive_reasons_in_points() -> None:
    contrib = {
        "days_to_next_payroll": 0.09,
        "pay_change_vs_3m_avg": 0.06,
        "answer_rate_after_18h": 0.04,
        "max_dpd": 0.01,
        "cash_flow_trend": -0.2,
    }
    r = top_reasons(contrib, {"days_to_next_payroll": 1}, templates=TEMPLATES)
    assert [x.feature for x in r] == ["days_to_next_payroll", "pay_change_vs_3m_avg", "answer_rate_after_18h"]
    assert [x.contribution_pts for x in r] == pytest.approx([9.0, 6.0, 4.0])
    assert r[0].sentence.startswith("Pay lands in 1 days")


def test_reasons_skip_untemplated_negative_and_non_model_features() -> None:
    contrib = {"cohort_kept_rate": 0.5, "hardship_signal": 0.4, "max_dpd": -0.1, "pay_change_vs_3m_avg": 0.02}
    r = top_reasons(contrib, {}, templates={**TEMPLATES, "hardship_signal": "Hardship"})
    assert [x.feature for x in r] == ["pay_change_vs_3m_avg"]


def test_reason_ties_broken_by_name() -> None:
    r = top_reasons(
        {"max_dpd": 0.05, "answer_rate_after_18h": 0.05}, {"max_dpd": 3}, templates=TEMPLATES, k=1
    )
    assert r[0].feature == "answer_rate_after_18h"


@pytest.mark.todo("Track D: write a fixed reason sentence for every model feature")
def test_every_model_feature_has_a_reason_template() -> None:
    missing = sorted(set(model_inputs()) - set(REASON_TEMPLATES))
    assert missing == []


def test_similar_cases_line() -> None:
    assert similar_cases_text(n=812, kept_rate_payday_plan=0.64, kept_rate_lump_sum=0.39) == (
        "812 past cases like this: 64% kept a payday-dated plan vs 39% a lump-sum promise (descriptive, not causal)."
    )
    assert similar_cases_text(n=49, kept_rate_payday_plan=0.64, kept_rate_lump_sum=0.39) is None


# ----------------------------------------------------------------- labels
def _payments(rows: list[tuple[float, float, bool]]) -> pd.DataFrame:
    return pd.DataFrame([{"paid_at": T0 + timedelta(days=d), "amount": a, "reversed": r} for d, a, r in rows])


@pytest.mark.parametrize(
    "rows,expected",
    [
        ([(1, 50.0, False)], True),
        ([(14, 50.0, False)], True),
        ([(14.01, 50.0, False)], False),
        ([(0, 50.0, False)], False),  # at decision time: not after
        ([(-1, 50.0, False)], False),
        ([(3, 50.0, True)], False),  # reversed
        ([(3, 0.0, False)], False),
        ([], False),
    ],
)
def test_paid_within_14_days(rows: list[tuple[float, float, bool]], expected: bool) -> None:
    df = _payments(rows) if rows else pd.DataFrame(columns=["paid_at", "amount", "reversed"])
    assert paid_within(df, decision_at=T0) is expected


@pytest.mark.parametrize(
    "entry,end,rolled",
    [
        (DpdBucket.B1_30, DpdBucket.B31_60, True),
        (DpdBucket.B1_30, DpdBucket.B1_30, False),
        (DpdBucket.B1_30, DpdBucket.CURRENT, False),
        (DpdBucket.B31_60, DpdBucket.B121_PLUS, True),
    ],
)
def test_rolled_forward(entry: DpdBucket, end: DpdBucket, rolled: bool) -> None:
    assert rolled_forward(entry, end) is rolled


def test_roll_forward_rate_uses_1_30_entry_cohort() -> None:
    cases = pd.DataFrame(
        {
            "entry_dpd": [5, 20, 30, 1, 45, 0],
            "dpd_at_day_30": [40, 25, 61, 0, 100, 40],
        }
    )
    # cohort = first four; rolled = 5->40, 30->61 -> 2/4
    assert roll_forward_rate(cases) == pytest.approx(0.5)
    with pytest.raises(ValueError):
        roll_forward_rate(cases[cases.entry_dpd > 30])


def test_roll_forward_rate_skips_cases_younger_than_30_days() -> None:
    cases = pd.DataFrame({"entry_dpd": [5, 10, 12], "dpd_at_day_30": [40, None, 0]})
    assert roll_forward_rate(cases) == pytest.approx(0.5)  # the null is not a cure
