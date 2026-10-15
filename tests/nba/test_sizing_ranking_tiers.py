"""Stages 5-6 and release tiers: Kept sizing, ranking within capacity, tier precedence."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_CEILING, Decimal

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from kept.contracts import Action, ActionScore, Channel, HardshipStatus, PayrollFrequency, ReleaseTier
from kept.nba.ranking import allocate_capacity, is_close_call, score_actions
from kept.nba.sizing import next_payday, promise_due_date, size_promise, sizing_text
from kept.nba.tiers import assign_tier

PAYDAY = date(2026, 10, 2)
TODAY = date(2026, 9, 28)


# ----------------------------------------------------------------- due dates
@pytest.mark.parametrize("offset,expected", [(0, date(2026, 10, 2)), (1, date(2026, 10, 3))])
def test_due_on_payday_or_the_day_after(offset: int, expected: date) -> None:
    assert promise_due_date(PAYDAY, today=TODAY, offset_days=offset) == expected


@pytest.mark.parametrize("offset", [2, 3, -1])
def test_due_offset_must_be_zero_or_one(offset: int) -> None:
    with pytest.raises(ValueError):
        promise_due_date(PAYDAY, today=TODAY, offset_days=offset)


def test_due_date_in_the_past_is_none() -> None:
    assert promise_due_date(PAYDAY, today=date(2026, 10, 1)) == date(2026, 10, 2)
    assert promise_due_date(PAYDAY, today=date(2026, 10, 2)) is None


# ----------------------------------------------------------------- sizing
def test_card_example_three_month_plan_of_140() -> None:
    s = size_promise(
        balance_due=Decimal("420.00"),
        spare_cash_monthly=Decimal("160.00"),
        expected_payday=PAYDAY,
        payroll_frequency=PayrollFrequency.MONTHLY,
        today=TODAY,
    )
    assert s is not None
    assert (s.amount, s.installments, s.due_date) == (Decimal("140.00"), 3, date(2026, 10, 2))
    assert s.spare_cash_estimate == Decimal("160.00") and s.payday == PAYDAY


def test_single_promise_when_it_fits() -> None:
    s = size_promise(
        balance_due=Decimal("100.00"),
        spare_cash_monthly=Decimal("160.00"),
        expected_payday=PAYDAY,
        payroll_frequency=PayrollFrequency.MONTHLY,
        today=TODAY,
    )
    assert s is not None and s.installments == 1 and s.amount == Decimal("100.00")


def test_amount_rounds_up_to_the_cent() -> None:
    s = size_promise(
        balance_due=Decimal("100.00"),
        spare_cash_monthly=Decimal("40.00"),
        expected_payday=PAYDAY,
        payroll_frequency=PayrollFrequency.MONTHLY,
        today=TODAY,
    )
    assert s is not None and s.amount == Decimal("33.34") and s.installments == 3


def test_biweekly_uses_spare_cash_per_period() -> None:
    # 160 x 12 / 26 = 73.846... -> 73.84 per pay period (rounded down)
    s = size_promise(
        balance_due=Decimal("200.00"),
        spare_cash_monthly=Decimal("160.00"),
        expected_payday=PAYDAY,
        payroll_frequency=PayrollFrequency.BIWEEKLY,
        today=TODAY,
    )
    assert s is not None and s.installments == 3 and s.amount == Decimal("66.67")
    assert s.spare_cash_estimate == Decimal("73.84")


@pytest.mark.parametrize(
    "kw",
    [
        {"spare_cash_monthly": None},
        {"spare_cash_monthly": Decimal("0")},
        {"spare_cash_monthly": Decimal("-50")},
        {"expected_payday": None},
        {"spare_cash_monthly": Decimal("100.00")},  # 420 needs 4.2 months > 3 installments
        {"today": date(2026, 10, 5)},  # payday already passed
    ],
)
def test_no_promise_when_it_cannot_be_kept(kw: dict[str, object]) -> None:
    base: dict[str, object] = dict(
        balance_due=Decimal("420.00"),
        spare_cash_monthly=Decimal("160.00"),
        expected_payday=PAYDAY,
        payroll_frequency=PayrollFrequency.MONTHLY,
        today=TODAY,
    )
    base.update(kw)
    assert size_promise(**base) is None  # type: ignore[arg-type]


money = st.decimals(min_value=Decimal("1.00"), max_value=Decimal("5000.00"), places=2)


@given(money, money, st.sampled_from(list(PayrollFrequency)), st.integers(min_value=1, max_value=6))
def test_sizing_invariants(balance: Decimal, spare: Decimal, freq: PayrollFrequency, max_inst: int) -> None:
    s = size_promise(
        balance_due=balance,
        spare_cash_monthly=spare,
        expected_payday=PAYDAY,
        payroll_frequency=freq,
        today=TODAY,
        max_installments=max_inst,
    )
    assume(s is not None)
    assert s is not None
    assert s.amount <= s.spare_cash_estimate  # within spare cash
    assert s.amount * s.installments >= balance  # covers the balance
    assert 1 <= s.installments <= max_inst
    assert s.due_date == PAYDAY  # due on payday
    if s.installments > 1:  # minimal: one fewer installment would not fit
        fewer = (balance / (s.installments - 1)).quantize(Decimal("0.01"), rounding=ROUND_CEILING)
        assert fewer > s.spare_cash_estimate


def test_sizing_text_matches_card() -> None:
    s = size_promise(
        balance_due=Decimal("420.00"),
        spare_cash_monthly=Decimal("160.00"),
        expected_payday=PAYDAY,
        payroll_frequency=PayrollFrequency.MONTHLY,
        today=TODAY,
    )
    assert s is not None
    t = sizing_text(s)
    assert "$140 " in t and "~$160" in t and "due on the expected payroll date" in t and ".00" not in t


# ----------------------------------------------------------------- ranking
P = {Action.WAIT: 0.22, Action.CALL: 0.58, Action.HARDSHIP_REVIEW: 0.47, Action.SMS_PAYMENT_LINK: 0.30}
COST = {
    Action.WAIT: Decimal(0),
    Action.CALL: Decimal("4.00"),
    Action.HARDSHIP_REVIEW: Decimal("8.00"),
    Action.SMS_PAYMENT_LINK: Decimal("0.10"),
}
BURDEN = {
    Action.WAIT: Decimal(0),
    Action.CALL: Decimal("2.00"),
    Action.HARDSHIP_REVIEW: Decimal("1.00"),
    Action.SMS_PAYMENT_LINK: Decimal("0.50"),
}


def test_score_formula_and_order() -> None:
    out = score_actions(p_paid=P, balance_at_risk=Decimal("420.00"), contact_cost=COST, burden=BURDEN)
    assert out[0].action is Action.CALL
    call = next(s for s in out if s.action is Action.CALL)
    assert call.uplift == pytest.approx(0.36)
    assert call.expected_value == pytest.approx(Decimal("151.20"))
    assert call.score == pytest.approx(Decimal("145.20"))
    wait = next(s for s in out if s.action is Action.WAIT)
    assert wait.uplift == 0 and wait.score == 0
    assert [s.score for s in out] == sorted((s.score for s in out), reverse=True)


def test_wait_required() -> None:
    with pytest.raises(ValueError):
        score_actions(p_paid={Action.CALL: 0.5}, balance_at_risk=Decimal(100), contact_cost={}, burden={})


def test_kept_smaller_plan_beats_broken_bigger_promise() -> None:
    out = score_actions(
        p_paid={Action.WAIT: 0.2, Action.PROMISE_REQUEST: 0.65, Action.PAYMENT_PLAN: 0.55},
        p_kept_given_promise={Action.PROMISE_REQUEST: 0.35, Action.PAYMENT_PLAN: 0.60},
        balance_at_risk=Decimal("420.00"),
        contact_cost={},
        burden={},
    )
    assert out[0].action is Action.PAYMENT_PLAN


def test_ties_broken_by_burden_then_declaration_order() -> None:
    out = score_actions(
        p_paid={Action.WAIT: 0.2, Action.EMAIL: 0.3, Action.PUSH: 0.3},
        balance_at_risk=Decimal(100),
        contact_cost={},
        burden={Action.EMAIL: Decimal(0), Action.PUSH: Decimal(0)},
    )
    assert [s.action for s in out[:2]] == [Action.EMAIL, Action.PUSH]


def _s(action: Action, score: float) -> ActionScore:
    return ActionScore(
        action=action,
        p_paid_14d=0.5,
        uplift=0.1,
        expected_value=Decimal(str(score)),
        contact_cost=Decimal(0),
        burden=Decimal(0),
        score=Decimal(str(score)),
    )


def test_capacity_respected_and_fallback() -> None:
    ranked = {
        "C-1": [_s(Action.CALL, 100), _s(Action.SMS_PAYMENT_LINK, 50), _s(Action.WAIT, 0)],
        "C-2": [_s(Action.CALL, 90), _s(Action.EMAIL, 40), _s(Action.WAIT, 0)],
        "C-3": [_s(Action.CALL, 80), _s(Action.SMS_PAYMENT_LINK, 70), _s(Action.WAIT, 0)],
    }
    out = allocate_capacity(ranked, {Channel.CALL: 2, Channel.SMS: 0, Channel.EMAIL: 5})
    assert out["C-1"].action is Action.CALL and out["C-2"].action is Action.CALL
    assert out["C-3"].action is Action.WAIT  # call full, SMS has no capacity


channels = st.fixed_dictionaries({c: st.integers(0, 3) for c in Channel})


@given(channels, st.integers(1, 12))
def test_capacity_never_exceeded_and_everyone_gets_one(cap: dict[Channel, int], n: int) -> None:
    from kept.contracts import ACTION_CHANNEL

    ranked = {
        f"C-{i}": [
            _s(Action.CALL, 100 - i),
            _s(Action.EMAIL, 50 - i),
            _s(Action.SMS_PAYMENT_LINK, 40),
            _s(Action.WAIT, 0),
        ]
        for i in range(n)
    }
    out = allocate_capacity(ranked, cap)
    assert set(out) == set(ranked)
    for ch, limit in cap.items():
        assert sum(1 for s in out.values() if ACTION_CHANNEL[s.action] is ch) <= limit


@pytest.mark.parametrize(
    "scores,expected", [([100, 99.5], True), ([100, 90], False), ([100], False), ([], False)]
)
def test_close_call(scores: list[float], expected: bool) -> None:
    acts = [Action.CALL, Action.PAYMENT_PLAN]
    assert is_close_call([_s(a, s) for a, s in zip(acts, scores, strict=False)], margin=0.02) is expected


# ----------------------------------------------------------------- tiers
@pytest.mark.parametrize(
    "kw,tier",
    [
        ({"action": Action.CALL, "hard_stopped": True}, ReleaseTier.BLOCKED),
        ({"action": Action.WAIT, "hard_stopped": True}, ReleaseTier.BLOCKED),
        ({"action": Action.CALL, "hardship_status": HardshipStatus.POSSIBLE}, ReleaseTier.RED),
        ({"action": Action.PAYMENT_PLAN, "hardship_status": HardshipStatus.CONFIRMED}, ReleaseTier.RED),
        ({"action": Action.PAYMENT_PLAN, "is_payment_reduction": True}, ReleaseTier.RED),
        ({"action": Action.PAYMENT_PLAN, "is_settlement": True}, ReleaseTier.RED),
        ({"action": Action.SMS_PAYMENT_LINK, "llm_agent_disagreement": True}, ReleaseTier.RED),
        ({"action": Action.CALL}, ReleaseTier.AMBER),
        ({"action": Action.PROMISE_REQUEST}, ReleaseTier.AMBER),
        ({"action": Action.PAYMENT_PLAN}, ReleaseTier.AMBER),
        ({"action": Action.HARDSHIP_REVIEW}, ReleaseTier.AMBER),
        ({"action": Action.SMS_PAYMENT_LINK, "close_call": True}, ReleaseTier.AMBER),
        ({"action": Action.SMS_PAYMENT_LINK}, ReleaseTier.GREEN),
        ({"action": Action.EMAIL}, ReleaseTier.GREEN),
        ({"action": Action.PUSH}, ReleaseTier.GREEN),
        ({"action": Action.WAIT}, ReleaseTier.GREEN),
    ],
)
def test_tiers(kw: dict[str, object], tier: ReleaseTier) -> None:
    base: dict[str, object] = {"hard_stopped": False, "hardship_status": HardshipStatus.NONE}
    base.update(kw)
    assert assign_tier(**base) is tier  # type: ignore[arg-type]


@given(
    st.sampled_from(list(Action)),
    st.sampled_from(list(HardshipStatus)),
    st.booleans(),
    st.booleans(),
    st.booleans(),
    st.booleans(),
)
def test_tier_precedence(
    action: Action, hs: HardshipStatus, red1: bool, red2: bool, red3: bool, close: bool
) -> None:
    base = assign_tier(
        action=action,
        hard_stopped=False,
        hardship_status=hs,
        is_payment_reduction=red1,
        is_settlement=red2,
        llm_agent_disagreement=red3,
        close_call=close,
    )
    assert assign_tier(action=action, hard_stopped=True, hardship_status=hs) is ReleaseTier.BLOCKED
    if hs is not HardshipStatus.NONE or red1 or red2 or red3:
        assert base is ReleaseTier.RED
    if action is Action.WAIT and not (hs is not HardshipStatus.NONE or red1 or red2 or red3 or close):
        assert base is ReleaseTier.GREEN


def test_next_payday_rolls_a_stale_payday_forward_on_the_schedule() -> None:
    today = date(2026, 10, 10)
    assert next_payday(date(2026, 10, 12), PayrollFrequency.BIWEEKLY, today=today) == date(2026, 10, 12)
    assert next_payday(date(2026, 9, 29), PayrollFrequency.BIWEEKLY, today=today) == date(2026, 10, 13)
    assert next_payday(date(2026, 10, 3), PayrollFrequency.WEEKLY, today=today) == today  # today counts
    assert next_payday(date(2026, 9, 29), PayrollFrequency.MONTHLY, today=today) == date(2026, 10, 29)
    assert next_payday(date(2026, 8, 31), PayrollFrequency.MONTHLY, today=date(2026, 9, 5)) == date(
        2026, 9, 30
    )
    assert next_payday(date(2026, 9, 29), PayrollFrequency.IRREGULAR, today=today) == date(2026, 9, 29)
    assert next_payday(None, PayrollFrequency.MONTHLY, today=today) is None
