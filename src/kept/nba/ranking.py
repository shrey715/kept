# ruff: noqa: E501  (docstrings)
"""Stage 6: rank by uplift x balance at risk - contact cost - burden, within daily capacity.

Costs: contact_history.contact_cost_cad (unit cost per attempt) and channel_capacity.unit_cost_cad.
Capacity: channel_capacity rows per (date, channel, time_band: 08-12 / 12-17 / 17-21 / all_day),
capacity_units - used_units. allocate_capacity takes one day's remaining units per channel;
time bands are applied when the call window is chosen.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from kept.config import CENT
from kept.contracts.enums import ACTION_CHANNEL, Action, Channel
from kept.contracts.nba import ActionScore, CaseContext

if TYPE_CHECKING:
    import pandas as pd

    from kept.nba.best_hour import BestHourModel

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
    (a kept smaller plan beats a broken bigger promise). The value is the whole chain, not P(kept | promise) alone:
    P(reach the right party) x P(promise made | reached) x P(kept | promise), because a customer who is not
    reached, or does not agree, never makes the promise (engine._ask_chain). Missing cost/burden -> 0.
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


class CallCapacity:
    """Hourly call capacity in the bank's operating time zone, booked as the nightly batch places calls.
    `units[(weekday, hour)]` is how many call attempts the team can make in that hour on that weekday
    (Monday 0); each date gets its own copy, used up as calls are booked into it. With `best_hour`,
    `book_best` picks the likeliest-to-answer slot on the earliest bookable day, not the earliest slot."""

    def __init__(
        self,
        units: Mapping[tuple[int, int], float],
        *,
        tz: str,
        length: timedelta,
        best_hour: BestHourModel | None = None,
    ) -> None:
        self.best_hour = best_hour
        self._units = dict(units)
        self._tz = ZoneInfo(tz)
        self._length = length
        self._left: dict[tuple[date, int], float] = {}

    def book(self, ctx: CaseContext, first: tuple[datetime, datetime]) -> tuple[datetime, datetime]:
        """The earliest half-hour slot from `first` inside the customer's own calling hours (up to a week
        ahead) whose operating hour still has capacity, booked. None free: `first`, unbooked."""
        local_tz = ZoneInfo(ctx.time_zone)
        start = first[0].astimezone(local_tz)
        for d in range(8):
            day = start.date() + timedelta(days=d)
            if day.weekday() == 6 and not ctx.sunday_contact_permitted:
                continue
            open_, close = (
                datetime.combine(day, t, local_tz)
                for t in (ctx.permitted_call_start_local, ctx.permitted_call_end_local)
            )
            s = max(open_, start)
            while s < close:
                op = s.astimezone(self._tz)
                key = (op.date(), op.hour)
                if key not in self._left:
                    self._left[key] = self._units.get((op.weekday(), op.hour), 0.0)
                if self._left[key] >= 1:
                    self._left[key] -= 1
                    return s.astimezone(UTC), min(s + self._length, close).astimezone(UTC)
                s += timedelta(minutes=30)
        return first

    def book_best(
        self, ctx: CaseContext, first: tuple[datetime, datetime], features: pd.DataFrame
    ) -> tuple[tuple[datetime, datetime], MovedCall | None]:
        """Like `book`, but of the half-hour slots with capacity on the same local day as the earliest
        (never a later day), books the one likeliest to reach the right party (`best_hour.p_rpc` on
        `features`, one row of the model inputs); a tie goes to the earlier slot. The second value says what
        moved, None if the earliest slot won. Needs `best_hour`; no free slot: `first`."""
        assert self.best_hour is not None
        local_tz = ZoneInfo(ctx.time_zone)
        start = first[0].astimezone(local_tz)
        for d in range(8):
            day = start.date() + timedelta(days=d)
            if day.weekday() == 6 and not ctx.sunday_contact_permitted:
                continue
            open_, close = (
                datetime.combine(day, t, local_tz)
                for t in (ctx.permitted_call_start_local, ctx.permitted_call_end_local)
            )
            free: list[tuple[datetime, tuple[date, int]]] = []
            s = max(open_, start)
            while s < close:
                op = s.astimezone(self._tz)
                key = (op.date(), op.hour)
                if key not in self._left:
                    self._left[key] = self._units.get((op.weekday(), op.hour), 0.0)
                if self._left[key] >= 1:
                    free.append((s, key))
                s += timedelta(minutes=30)
            if not free:
                continue
            p = self.best_hour.p_rpc(features, [(s.hour, s.weekday()) for s, _ in free])
            i = int(p.argmax())  # the first maximum: ties go to the earlier slot
            s, key = free[i]
            self._left[key] -= 1
            moved = MovedCall(s, free[0][0], float(p[i]), float(p[0])) if i else None
            return (s.astimezone(UTC), min(s + self._length, close).astimezone(UTC)), moved
        return first, None


@dataclass(frozen=True)
class MovedCall:
    """A call booked after its earliest slot because the customer likelier answers then (customer-local)."""

    booked: datetime
    earliest: datetime
    p_booked: float
    p_earliest: float

    def text(self) -> str:
        return (
            f"Booked {self.booked:%H:%M}: this customer is likelier to answer then "
            f"({self.p_booked:.0%} chance of reaching them, "
            f"against {self.p_earliest:.0%} at {self.earliest:%H:%M})."
        )
