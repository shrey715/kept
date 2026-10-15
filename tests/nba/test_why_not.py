from decimal import Decimal

from kept.contracts.enums import Action
from kept.contracts.nba import ActionScore
from kept.nba.engine import why_not


def s(a: Action, uplift: float, score: str) -> ActionScore:
    return ActionScore(
        action=a,
        p_paid_14d=0.3 + uplift,
        uplift=uplift,
        expected_value=Decimal(score),
        contact_cost=Decimal(0),
        burden=Decimal(0),
        score=Decimal(score),
    )


def test_why_not_compares_with_the_best_other_kind_of_action() -> None:
    ranked = [
        s(Action.PROMISE_REQUEST, 0.05, "12"),
        s(Action.CALL, 0.05, "12"),
        s(Action.SMS_PAYMENT_LINK, 0.02, "7.5"),
        s(Action.WAIT, 0.0, "0"),
    ]
    text = why_not(ranked[0], ranked)
    assert (
        text is not None
        and "5.0 points" in text
        and "to text a payment link adds 2.0" in text
        and "$4.50 more" in text
    )


def test_why_not_when_protection_overrides_value_and_when_waiting_is_next() -> None:
    ranked = [
        s(Action.SMS_PAYMENT_LINK, 0.04, "9"),
        s(Action.HARDSHIP_REVIEW, 0.01, "2"),
        s(Action.WAIT, 0.0, "0"),
    ]
    assert "protections come first" in (why_not(ranked[1], ranked) or "")
    assert "more than waiting" in (why_not(ranked[0], [ranked[0], ranked[2]]) or "")
    assert why_not(ranked[2], ranked) is None


def test_protection_over_waiting_never_reads_as_a_negative_gain() -> None:
    ranked = [s(Action.WAIT, 0.0, "0"), s(Action.HARDSHIP_REVIEW, -0.045, "-77.57")]
    text = why_not(ranked[1], ranked) or ""
    assert text.startswith("Waiting would be worth $77.57 more") and "-" not in text
