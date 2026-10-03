"""Bank codes -> our Action enum (kill switch, hold-out, training rows)."""

from __future__ import annotations

import pytest

from kept.contracts import Action
from kept.nba.legacy import legacy_to_action, treatment_to_action


@pytest.mark.parametrize(
    "code,action",
    [
        ("call_evening", Action.CALL),  # dictionary example for nba_recommendation_last
        ("call_daytime", Action.CALL),
        ("sms_payment_link", Action.SMS_PAYMENT_LINK),
        ("offer_hardship_plan", Action.HARDSHIP_REVIEW),
        ("send_letter", None),  # we don't send letters
        ("CALL_EVENING", Action.CALL),
        (None, None),
        ("", None),
        ("teleport", None),
    ],
)
def test_legacy_to_action(code: str | None, action: Action | None) -> None:
    assert legacy_to_action(code) is action


@pytest.mark.parametrize(
    "treatment,channel,action",
    [
        ("payment_link", "sms", Action.SMS_PAYMENT_LINK),  # dictionary example treatment_code
        ("outbound_call", "call", Action.CALL),  # dictionary example current_treatment
        ("email_reminder", "email", Action.EMAIL),
        ("push", "push", Action.PUSH),
        ("letter", "letter", None),
        ("payment_link", "email", None),  # treatment and channel must agree
        (None, "call", None),
        ("mystery", "sms", None),
    ],
)
def test_treatment_to_action(treatment: str | None, channel: str | None, action: Action | None) -> None:
    assert treatment_to_action(treatment, channel) is action
