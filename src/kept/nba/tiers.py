"""Release tiers (design §6 table). Precedence: BLOCKED > RED > AMBER > GREEN."""

from __future__ import annotations

from kept.contracts.enums import Action, HardshipStatus, ReleaseTier

GREEN_ACTIONS = frozenset({Action.EMAIL, Action.PUSH, Action.SMS_PAYMENT_LINK})


def assign_tier(
    *,
    action: Action,
    hard_stopped: bool,
    hardship_status: HardshipStatus,
    is_payment_reduction: bool = False,
    is_settlement: bool = False,
    llm_agent_disagreement: bool = False,
    close_call: bool = False,
) -> ReleaseTier:
    """BLOCKED: any hard stop.
    RED: possible or confirmed hardship, payment reductions, settlement, LLM vs agent disagreement.
    AMBER: calls, promises, plans, hardship review; any close call between top two.
    GREEN: template reminders (email, push) and SMS links.
    WAIT needs no release: return GREEN unless a stronger rule applies."""
    if hard_stopped:
        return ReleaseTier.BLOCKED
    if (
        hardship_status is not HardshipStatus.NONE
        or is_payment_reduction
        or is_settlement
        or llm_agent_disagreement
    ):
        return ReleaseTier.RED
    if close_call or (action not in GREEN_ACTIONS and action is not Action.WAIT):
        return ReleaseTier.AMBER
    return ReleaseTier.GREEN
