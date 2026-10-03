"""Stage 6: rank by uplift x balance at risk - contact cost - burden, within daily capacity.

Costs: contact_history.contact_cost_cad (unit cost per attempt) and channel_capacity.unit_cost_cad.
Capacity: channel_capacity rows per (date, channel, time_band: 08-12 / 12-17 / 17-21 / all_day),
capacity_units - used_units. allocate_capacity takes one day's remaining units per channel;
time bands are applied when the call window is chosen.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal

from kept.config import CENT
from kept.contracts.enums import ACTION_CHANNEL, Action, Channel
from kept.contracts.nba import ActionScore

_ORDER = {a: i for i, a in enumerate(Action)}
_KEPT_SIZED = (Action.PROMISE_REQUEST, Action.PAYMENT_PLAN)


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
    if Action.WAIT not in p_paid:
        raise ValueError("p_paid must include WAIT (the baseline)")
    base = p_paid[Action.WAIT]
    kept = p_kept_given_promise or {}
    out = []
    for a, p in p_paid.items():
        lift = (kept[a] if a in _KEPT_SIZED and a in kept else p) - base
        ev = (Decimal(str(lift)) * balance_at_risk).quantize(CENT)
        cost, load = contact_cost.get(a, Decimal(0)), burden.get(a, Decimal(0))
        out.append(
            ActionScore(
                action=a,
                p_paid_14d=p,
                uplift=p - base,
                expected_value=ev,
                contact_cost=cost,
                burden=load,
                score=(ev - cost - load).quantize(CENT),
            )
        )
    return sorted(out, key=lambda s: (-s.score, s.burden, _ORDER[s.action]))


def allocate_capacity(
    ranked_by_case: Mapping[str, Sequence[ActionScore]],
    capacity: Mapping[Channel, int],
) -> dict[str, ActionScore]:
    """Daily batch: give each case its best action whose channel still has capacity,
    processing cases in order of their best score desc; fall back down each case's list;
    WAIT needs no capacity. Every case gets exactly one action. Channel use never
    exceeds capacity."""
    left = dict(capacity)
    order = sorted(
        ranked_by_case, key=lambda c: -max((s.score for s in ranked_by_case[c]), default=Decimal(0))
    )
    out: dict[str, ActionScore] = {}
    for case_id in order:
        for s in ranked_by_case[case_id]:
            ch = ACTION_CHANNEL[s.action]
            if ch is None or left.get(ch, 0) > 0:
                if ch is not None:
                    left[ch] -= 1
                out[case_id] = s
                break
        else:  # no WAIT in the list and every channel full: waiting needs no capacity
            out[case_id] = ActionScore(
                action=Action.WAIT,
                p_paid_14d=0.0,
                uplift=0.0,
                expected_value=Decimal(0),
                contact_cost=Decimal(0),
                burden=Decimal(0),
                score=Decimal(0),
            )
    return out


def is_close_call(ranked: Sequence[ActionScore], *, margin: float) -> bool:
    """True when the top two scores differ by less than margin x |top score|.
    Fewer than two actions -> False."""
    if len(ranked) < 2:
        return False
    top, second = ranked[0].score, ranked[1].score
    return abs(top - second) < Decimal(str(margin)) * abs(top)
