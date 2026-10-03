"""Stages 1-3: rules before the model. No AI here."""

from __future__ import annotations

from collections.abc import Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from kept.contracts.enums import ACTION_CHANNEL, HARDSHIP_ALLOWED_ACTIONS, Action, HardshipStatus, HardStop
from kept.contracts.nba import CaseContext, CheckName, CheckResult, HardStopResult, PermissionResult

# What the agent reads on the rule card, one line per stop.
_STOP_REASON = {
    HardStop.CEASE: "cease: the customer asked us to stop contacting them",
    HardStop.INSOLVENCY: "insolvency: consumer proposal or insolvency hold, collection is stayed",
    HardStop.BANKRUPTCY: "bankruptcy: bankruptcy on file, collection is stayed",
    HardStop.DECEASED: "deceased: refer to the estates process",
}


def hard_stops(ctx: CaseContext) -> HardStopResult:
    """Blocked if any flag in ctx.hard_stop_flags is set (cease, insolvency, bankruptcy,
    deceased). fired lists every rule that fired, in HardStop declaration order;
    rule_card names each one for the agent. No flags -> not blocked, rule_card None."""
    fired = tuple(h for h in HardStop if h in ctx.hard_stop_flags)
    if not fired:
        return HardStopResult(blocked=False)
    card = "No contact. " + "; ".join(_STOP_REASON[h] for h in fired) + "."
    return HardStopResult(blocked=True, fired=fired, rule_card=card)


def permission_gate(ctx: CaseContext, action: Action) -> PermissionResult:
    """Checks for contact actions (every action except WAIT):
      DO_NOT_CONTACT  ctx.do_not_contact is False
      CONSENT         consent for ACTION_CHANNEL[action]
      CALLING_HOURS   ctx.now, in ctx.time_zone (DST-aware), is inside the customer's own
                      [permitted_call_start_local, permitted_call_end_local), and not a Sunday
                      unless sunday_contact_permitted
      CONTACT_CAP     ctx.contacts_last_7d < ctx.contact_cap_7d (per case); detail "n of cap"
    WAIT is always allowed with no checks. Unknown time zone -> fail CALLING_HOURS (closed)."""
    channel = ACTION_CHANNEL[action]
    if channel is None:
        return PermissionResult(action=action, allowed=True, checks=())
    consent = bool(getattr(ctx.contact_permissions, channel.value))
    checks = (
        CheckResult(
            check=CheckName.DO_NOT_CONTACT,
            passed=not ctx.do_not_contact,
            detail="on the do-not-contact list" if ctx.do_not_contact else "not on the do-not-contact list",
        ),
        CheckResult(
            check=CheckName.CONSENT,
            passed=consent,
            detail=f"{channel.value} consent {'given' if consent else 'missing'}",
        ),
        _calling_hours(ctx),
        CheckResult(
            check=CheckName.CONTACT_CAP,
            passed=ctx.contacts_last_7d < ctx.contact_cap_7d,
            detail=f"{ctx.contacts_last_7d} of {ctx.contact_cap_7d} contacts this week",
        ),
    )
    return PermissionResult(action=action, allowed=all(c.passed for c in checks), checks=checks)


def _calling_hours(ctx: CaseContext) -> CheckResult:
    try:
        local = ctx.now.astimezone(ZoneInfo(ctx.time_zone))
    except (ZoneInfoNotFoundError, ValueError):
        return CheckResult(check=CheckName.CALLING_HOURS, passed=False, detail=f"unknown time zone {ctx.time_zone!r}")
    start, end = ctx.permitted_call_start_local, ctx.permitted_call_end_local
    window = f"{local:%a %H:%M} local, window {start:%H:%M}-{end:%H:%M}"
    if local.weekday() == 6 and not ctx.sunday_contact_permitted:
        return CheckResult(check=CheckName.CALLING_HOURS, passed=False, detail=f"{window}; no Sunday contact")
    ok = start <= local.time() < end
    return CheckResult(check=CheckName.CALLING_HOURS, passed=ok, detail=window)


def allowed_actions(
    ctx: CaseContext, candidates: Iterable[Action] = tuple(Action)
) -> tuple[list[Action], list[PermissionResult]]:
    """Run the permission gate on every candidate. WAIT always survives."""
    results = [permission_gate(ctx, a) for a in candidates]
    return [r.action for r in results if r.allowed], results


def hardship_override(ctx: CaseContext, actions: Iterable[Action]) -> list[Action]:
    """If hardship_status is POSSIBLE or CONFIRMED, or ctx.vulnerable, keep only HARDSHIP_ALLOWED_ACTIONS
    (check-in call, hardship review, payment plan, wait). Otherwise unchanged.
    Preserves input order."""
    if ctx.hardship_status is HardshipStatus.NONE and not ctx.vulnerable:
        return list(actions)
    return [a for a in actions if a in HARDSHIP_ALLOWED_ACTIONS]
