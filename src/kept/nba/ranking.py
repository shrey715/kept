"""Stage 6: rank by uplift x balance at risk - contact cost - burden, within daily capacity.

Costs: contact_history.contact_cost_cad (unit cost per attempt) and channel_capacity.unit_cost_cad.
Capacity: channel_capacity rows per (date, channel, time_band: 08-12 / 12-17 / 17-21 / all_day),
capacity_units - used_units. allocate_capacity takes one day's remaining units per channel;
time bands are applied when the call window is chosen.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal

from kept.contracts.enums import Action, Channel
from kept.contracts.nba import ActionScore


def score_actions(
    *,
    p_paid: Mapping[Action, float],
    balance_at_risk: Decimal,
    contact_cost: Mapping[Action, Decimal],
    burden: Mapping[Action, Decimal],
    p_kept_given_promise: Mapping[Action, float] | None = None,
) -> list[ActionScore]:
    """One ActionScore per action in p_paid. uplift = p_paid[a] - p_paid[WAIT]
    (WAIT must be present, else ValueError). expected_value = uplift x balance_at_risk, except
    for PROMISE_REQUEST/PAYMENT_PLAN when p_kept_given_promise has the action: then
    expected_value = (p_kept_given_promise[a] - p_paid[WAIT]) x balance_at_risk
    (a kept smaller plan beats a broken bigger promise). Missing cost/burden -> 0.
    Sorted by score desc; ties broken by lower burden, then Action declaration order."""
    raise NotImplementedError("Track D")


def allocate_capacity(
    ranked_by_case: Mapping[str, Sequence[ActionScore]],
    capacity: Mapping[Channel, int],
) -> dict[str, ActionScore]:
    """Daily batch: give each case its best action whose channel still has capacity,
    processing cases in order of their best score desc; fall back down each case's list;
    WAIT needs no capacity. Every case gets exactly one action. Channel use never
    exceeds capacity."""
    raise NotImplementedError("Track D")


def is_close_call(ranked: Sequence[ActionScore], *, margin: float) -> bool:
    """True when the top two scores differ by less than margin x |top score|.
    Fewer than two actions -> False."""
    raise NotImplementedError("Track D")
