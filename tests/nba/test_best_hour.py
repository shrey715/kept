"""Best-hour booking: with the switch off booking is unchanged (test_call_capacity.py); on, a call takes the likeliest-to-answer
slot of the earliest bookable local day, inside the customer's hours, with capacity, and never a later day."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Any
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
    assert (
        moved.text()
        == "Booked 18:00: this customer is likelier to answer then (60% chance of reaching them, against 30% at 08:00)."
    )


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

    # the model keeps its own columns: a feature added to the registry later (and so to the frame) changes nothing
    wider = rows.iloc[[0, 0]].assign(brand_new_input=1.0)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("kept.nba.best_hour.model_inputs", lambda: [*model_inputs(), "brand_new_input"])
        assert (model.p_rpc(wider.iloc[[0]], [(9, 2), (18, 2)]) == p).all()
        assert (
            model.p_rows(wider, [9, 18], [2, 2]) == model.p_rows(rows.iloc[[0, 0]], [9, 18], [2, 2])
        ).all()
        del model._columns  # a pickle from before the columns were stored uses the registry's current list
        with pytest.raises(KeyError):  # ... which here has the extra input, absent from `rows`
            model.p_rpc(rows.iloc[[0]], [(9, 2)])


@pytest.mark.parametrize("on", [False, True])
def test_the_card_says_when_best_hour_moved_the_call(make_ctx: Any, on: bool) -> None:
    from kept.contracts import FeatureVector
    from kept.nba.engine import KeptEngine

    from ..fakes import ConstantScorer, FixedContextBuilder, InMemoryAuditLog, StaticFeatureProvider

    now = datetime(2026, 10, 2, 22, 0, tzinfo=UTC)
    ctx = make_ctx()
    fv = FeatureVector(
        case_id=ctx.case_id,
        golden_customer_id=ctx.golden_customer_id,
        as_of=ctx.features_as_of,
        feature_set_version="fs-0",
        max_dpd=18,
        days_to_next_payroll=0,
    )
    probs = {
        "wait": 0.22,
        "email": 0.25,
        "push": 0.23,
        "sms_payment_link": 0.30,
        "call": 0.58,
        "promise_request": 0.40,
        "payment_plan": 0.50,
        "hardship_review": 0.47,
    }
    cap = CallCapacity(
        {(w, h): 50 for w in range(7) for h in range(24)},
        tz="America/Toronto",
        length=timedelta(hours=2),
        best_hour=ByHour({19: 0.7}) if on else None,
    )  # type: ignore[arg-type]
    eng = KeptEngine(
        context=FixedContextBuilder({ctx.case_id: ctx}), features=StaticFeatureProvider({ctx.case_id: fv}),
        scorer=ConstantScorer(probs, model_version="nba-0.3"), audit_log=InMemoryAuditLog(), call_capacity=cap,
    )  # fmt: skip
    card = eng.recommend(ctx.case_id, now)
    p = card.proposal
    assert p is not None and p.window_start is not None
    local = p.window_start.astimezone(ZoneInfo("America/Toronto"))
    if on:
        assert (
            local.hour == 19
            and "Booked 19:00" in (card.why_not_text or "")
            and "70%" in (card.why_not_text or "")
        )
        assert "19:00" in card.headline
    else:
        assert local.hour < 19 and "Booked" not in (card.why_not_text or "")


def test_booking_is_on_by_default_when_the_model_exists(tmp_path: Any) -> None:
    from kept.nba.best_hour import BestHourModel, save
    from kept.nba.score import _hour_model

    path = tmp_path / "best_hour.pkl"
    assert _hour_model(None, path) is None and _hour_model(False, path) is None  # no model: the earliest slot
    with pytest.raises(FileNotFoundError):
        _hour_model(True, path)  # asked for it explicitly: say so
    save(BestHourModel(None, "v", ["a"]), path)
    assert _hour_model(None, path) is not None and _hour_model(True, path) is not None
    assert _hour_model(False, path) is None  # --no-best-hour / KEPT_BEST_HOUR=0


def test_the_nightly_retrains_the_model_weekly_before_scoring(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import argparse
    import os
    import time

    import duckdb

    from kept import cli

    names = [n for n, _ in cli.NIGHTLY]
    assert names.index("parity") < names.index("train-best-hour") < names.index("score")
    argv = dict(cli.NIGHTLY)["train-best-hour"]
    assert argv[-2:] == ["--if-older-than", "7"]

    out = tmp_path / "best_hour.pkl"
    out.write_bytes(b"x")
    args = argparse.Namespace(out=out, if_older_than=7.0, cutoff=datetime(2026, 8, 15))
    assert cli.train_best_hour(args) == 0 and out.read_bytes() == b"x"  # fresh: left alone

    def opened(*a: Any, **k: Any) -> None:
        raise RuntimeError("opened the warehouse")

    monkeypatch.setattr(duckdb, "connect", opened)
    old = time.time() - 8 * 86400
    os.utime(out, (old, old))
    with pytest.raises(RuntimeError, match="opened the warehouse"):
        cli.train_best_hour(args)  # a week old: it goes to retrain
