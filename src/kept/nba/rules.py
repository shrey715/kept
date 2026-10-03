"""Stages 1-3: rules before the model. No AI here."""

from __future__ import annotations

from collections.abc import Iterable

from kept.contracts.enums import Action
from kept.contracts.nba import CaseContext, HardStopResult, PermissionResult


def hard_stops(ctx: CaseContext) -> HardStopResult:
    """Blocked if any flag in ctx.hard_stop_flags is set (cease, insolvency, bankruptcy,
    deceased). fired lists every rule that fired, in HardStop declaration order;
    rule_card names each one for the agent. No flags -> not blocked, rule_card None."""
    raise NotImplementedError("Track D")


def permission_gate(ctx: CaseContext, action: Action) -> PermissionResult:
    """Checks for contact actions (every action except WAIT):
      DO_NOT_CONTACT  ctx.do_not_contact is False
      CONSENT         consent for ACTION_CHANNEL[action]
      CALLING_HOURS   ctx.now, in ctx.time_zone (DST-aware), is inside the customer's own
                      [permitted_call_start_local, permitted_call_end_local), and not a Sunday
                      unless sunday_contact_permitted
      CONTACT_CAP     ctx.contacts_last_7d < ctx.contact_cap_7d (per case); detail "n of cap"
    WAIT is always allowed with no checks. Unknown time zone -> fail CALLING_HOURS (closed)."""
    raise NotImplementedError("Track D")


def allowed_actions(
    ctx: CaseContext, candidates: Iterable[Action] = tuple(Action)
) -> tuple[list[Action], list[PermissionResult]]:
    """Run the permission gate on every candidate. WAIT always survives."""
    raise NotImplementedError("Track D")


def hardship_override(ctx: CaseContext, actions: Iterable[Action]) -> list[Action]:
    """If hardship_status is POSSIBLE or CONFIRMED, or ctx.vulnerable, keep only HARDSHIP_ALLOWED_ACTIONS
    (check-in call, hardship review, payment plan, wait). Otherwise unchanged.
    Preserves input order."""
    raise NotImplementedError("Track D")
