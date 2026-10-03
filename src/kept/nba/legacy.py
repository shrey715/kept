"""Translate the bank's codes into our Action enum (Track D).

collections_cases.nba_recommendation_last is the incumbent rules engine's output
("call_evening"); contact_history.treatment_code + channel say what was actually done
("payment_link" over "sms"). The kill switch and hold-out need the first; uplift training
needs the second. Full code lists live in code_lookups: extend the tables, keep the tests.
"""

from __future__ import annotations

from kept.contracts.enums import Action

# Every value in the real data (3 Oct 2026). send_letter / letter have no Action: we don't send letters.
_LEGACY = {
    "sms_payment_link": Action.SMS_PAYMENT_LINK,
    "call_evening": Action.CALL,
    "call_daytime": Action.CALL,
    "offer_hardship_plan": Action.HARDSHIP_REVIEW,
}
_TREATMENT = {
    ("outbound_call", "call"): Action.CALL,
    ("payment_link", "sms"): Action.SMS_PAYMENT_LINK,
    ("email_reminder", "email"): Action.EMAIL,
    ("push", "push"): Action.PUSH,
}


def legacy_to_action(code: str | None) -> Action | None:
    """Incumbent recommendation -> Action. Time-of-day suffixes are dropped
    ("call_evening" -> CALL). Unknown or empty code -> None (caller shows no action)."""
    code = (code or "").strip().lower()
    if code.startswith("call_"):
        return Action.CALL
    return _LEGACY.get(code)


def treatment_to_action(treatment_code: str | None, channel: str | None) -> Action | None:
    """What a past contact did, for training rows. ("payment_link", "sms") -> SMS_PAYMENT_LINK,
    ("outbound_call", "call") -> CALL. Channel is read from channel_v2 or channel (schema
    drift, see kept.data.traps.coalesce_renamed). Unknown -> None (row dropped from training)."""
    if treatment_code is None or channel is None:
        return None
    return _TREATMENT.get((treatment_code.strip().lower(), channel.strip().lower()))
