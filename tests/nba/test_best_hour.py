"""Best-hour booking: with the switch off booking is unchanged (test_call_capacity.py); on, a call takes the likeliest-to-answer
slot of the earliest bookable local day, inside the customer's hours, with capacity, and never a later day."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from kept.contracts.feature_registry import model_inputs
from kept.features.store import assert_no_denied
from kept.nba.ranking import CallCapacity


class Ctx:
    time_zone = "America/Toronto"
    permitted_call_start_local = time(8, 0)
    permitted_call_end_local = time(21, 0)
    sunday_contact_permitted = False


class ByHour:
    """A stand-in model: the chance of reaching the customer, by local hour."""

    def __init__(self, p: dict[int, float]) -> None:
        self.p = p

    def p_rpc(self, features: pd.DataFrame, slots: list[tuple[int, int]]) -> np.ndarray:
        return np.array([self.p.get(h, 0.1) for h, _ in slots])


def _book(units: dict[tuple[int, int], float], p: dict[int, float]) -> CallCapacity:
    return CallCapacity(units, tz="America/Toronto", length=timedelta(hours=2), best_hour=ByHour(p))  # type: ignore[arg-type]


THU_8AM = (datetime(2026, 10, 15, 12, 0, tzinfo=UTC), datetime(2026, 10, 15, 14, 0, tzinfo=UTC))  # 08:00 EDT
X = pd.DataFrame([{}])


def _local(slot: tuple[datetime, datetime]) -> datetime:
    return slot[0].astimezone(ZoneInfo("America/Toronto"))


def test_picks_the_likelier_hour_on_the_same_day_and_ties_go_to_the_earlier_slot() -> None:
    cap = _book({(3, h): 5 for h in range(8, 21)}, {18: 0.6, 19: 0.6, 8: 0.3})
    slot, moved = cap.book_best(Ctx(), THU_8AM, X)  # type: ignore[arg-type]
    assert _local(slot).hour == 18 and _local(slot).minute == 0  # 18:00 and 19:00 tie: the earlier
    assert moved is not None and moved.p_booked == 0.6 and moved.p_earliest == 0.3
    assert moved.text() == "Booked 18:00: this customer is likelier to answer then (60% chance of reaching them, against 30% at 08:00)."


def test_the_earliest_slot_wins_when_it_is_the_best_and_nothing_is_reported() -> None:
    cap = _book({(3, h): 5 for h in range(8, 21)}, {8: 0.7, 18: 0.6})
    slot, moved = cap.book_best(Ctx(), THU_8AM, X)  # type: ignore[arg-type]
    assert slot == THU_8AM and moved is None


def test_only_slots_with_capacity_inside_the_customers_hours() -> None:
    class Narrow(Ctx):
        permitted_call_start_local = time(9, 0)
        permitted_call_end_local = time(17, 0)

    # the best hour (20:00) is outside the window; 11:00 has no capacity; 15:00 is the best of what is left
    units = {(3, h): 5 for h in range(8, 21) if h != 11}
    cap = _book(units, {20: 0.9, 11: 0.8, 15: 0.5})
    slot, moved = cap.book_best(Narrow(), THU_8AM, X)  # type: ignore[arg-type]
    s, e = _local(slot), slot[1].astimezone(ZoneInfo("America/Toronto"))
    assert s.hour == 15 and time(9) <= s.time() and e.time() <= time(17)
    assert moved is not None


def test_never_a_later_day_than_the_earliest_bookable_slot() -> None:
    # Thursday has no capacity at all: the earliest slot is Friday 08:00, so the call stays on Friday even though
    # Saturday 19:00 would be likelier
    cap = _book({(4, h): 5 for h in range(8, 21)} | {(5, 19): 9}, {19: 0.9, 12: 0.4})
    slot, _ = cap.book_best(Ctx(), THU_8AM, X)  # type: ignore[arg-type]
    assert _local(slot).date().isoformat() == "2026-10-16" and _local(slot).hour == 19


def test_capacity_is_used_up_by_the_chosen_hour_only() -> None:
    cap = _book({(3, 8): 5, (3, 18): 1, (3, 19): 1}, {18: 0.7, 19: 0.6, 8: 0.3})
    hours = [_local(cap.book_best(Ctx(), THU_8AM, X)[0]).hour for _ in range(4)]  # type: ignore[arg-type]
    assert hours == [18, 19, 8, 8]  # 18:00 and 19:00 hold one call each; then only 08:00 is left that day
    assert cap._left[(datetime(2026, 10, 15).date(), 8)] == 3  # 5 units, two booked
    assert cap._left[(datetime(2026, 10, 15).date(), 18)] == 0


def test_no_free_slot_returns_the_first_one_unbooked() -> None:
    cap = _book({}, {})
    assert cap.book_best(Ctx(), THU_8AM, X) == (THU_8AM, None)  # type: ignore[arg-type]


def test_switch_off_booking_is_the_earliest_slot_as_before() -> None:
    cap = CallCapacity({(3, h): 5 for h in range(8, 21)}, tz="America/Toronto", length=timedelta(hours=2))
    assert cap.best_hour is None and cap.book(Ctx(), THU_8AM) == THU_8AM  # type: ignore[arg-type]


def test_the_model_inputs_are_registry_inputs_with_no_protected_attribute() -> None:
    from kept.nba.best_hour import slot_columns

    assert_no_denied(pd.DataFrame(columns=slot_columns()))
    assert set(slot_columns()) == {*model_inputs(), "hour", "weekday"}


def test_trained_model_prefers_the_evening_when_the_data_say_so() -> None:
    pytest.importorskip("lightgbm")
    from kept.nba.best_hour import train

    rng = np.random.default_rng(0)
    n = 6_000
    rows = pd.DataFrame({c: rng.normal(size=n) for c in model_inputs() if c != "pay_frequency"})
    rows["pay_frequency"] = "monthly"
    rows["promise_intent"] = rng.integers(0, 2, n).astype(float)
    rows["hour"], rows["weekday"] = rng.integers(8, 21, n), rng.integers(0, 7, n)
    rows["rpc"] = rng.uniform(size=n) < np.where(rows.hour >= 17, 0.65, 0.35)
    rows["decision_at"] = datetime(2026, 7, 1)
    rows.loc[: n // 4, "decision_at"] = datetime(2026, 9, 1)
    model, metrics = train(rows)
    p = model.p_rpc(rows.iloc[[0]], [(9, 2), (18, 2)])
    assert p[1] > p[0] + 0.15 and metrics["auc_test"] > 0.6
