"""Translate the bank's codes into our Action enum (Track D).

collections_cases.nba_recommendation_last is the incumbent rules engine's output
("call_evening"); contact_history.treatment_code + channel say what was actually done
("payment_link" over "sms"). The kill switch and hold-out need the first; uplift training
needs the second. Full code lists live in code_lookups: extend the tables, keep the tests.
"""

from __future__ import annotations

from kept.contracts.enums import Action


def legacy_to_action(code: str | None) -> Action | None:
    """Incumbent recommendation -> Action. Time-of-day suffixes are dropped
    ("call_evening" -> CALL). Unknown or empty code -> None (caller shows no action)."""
    raise NotImplementedError("Track D")


def treatment_to_action(treatment_code: str | None, channel: str | None) -> Action | None:
    """What a past contact did, for training rows. ("payment_link", "sms") -> SMS_PAYMENT_LINK,
    ("outbound_call", "call") -> CALL. Channel is read from channel_v2 or channel (schema
    drift, see kept.data.traps.coalesce_renamed). Unknown -> None (row dropped from training)."""
    raise NotImplementedError("Track D")
