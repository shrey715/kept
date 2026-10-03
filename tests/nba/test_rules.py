"""Stages 1-3: hard stops, permission gate (consent, local hours, 7-day cap), hardship override."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from kept.contracts import (
    HARDSHIP_ALLOWED_ACTIONS,
    Action,
    CaseContext,
    ContactPermissions,
    HardshipStatus,
    HardStop,
)
from kept.contracts.nba import CheckName
from kept.nba.rules import allowed_actions, hard_stops, hardship_override, permission_gate

Ctx = Callable[..., CaseContext]
CONTACT_ACTIONS = [a for a in Action if a is not Action.WAIT]


# ----------------------------------------------------------------- hard stops
def test_no_flags_not_blocked(make_ctx: Ctx) -> None:
    r = hard_stops(make_ctx())
    assert not r.blocked and r.fired == () and r.rule_card is None


@pytest.mark.parametrize("flag", list(HardStop))
def test_each_flag_blocks_and_is_named(make_ctx: Ctx, flag: HardStop) -> None:
    r = hard_stops(make_ctx(hard_stop_flags=frozenset({flag})))
    assert r.blocked and r.fired == (flag,)
    assert r.rule_card and flag.value in r.rule_card.lower()


def test_all_fired_rules_listed_in_declaration_order(make_ctx: Ctx) -> None:
    r = hard_stops(make_ctx(hard_stop_flags=frozenset({HardStop.DECEASED, HardStop.CEASE})))
    assert r.fired == (HardStop.CEASE, HardStop.DECEASED)


# ----------------------------------------------------------------- permission gate
def test_wait_always_allowed(make_ctx: Ctx) -> None:
    ctx = make_ctx(do_not_contact=True, contact_permissions=ContactPermissions(), contacts_last_7d=99)
    r = permission_gate(ctx, Action.WAIT)
    assert r.allowed and r.checks == ()


@pytest.mark.parametrize("action", CONTACT_ACTIONS)
def test_contact_actions_allowed_when_everything_passes(make_ctx: Ctx, action: Action) -> None:
    r = permission_gate(make_ctx(), action)
    assert r.allowed
    assert {c.check for c in r.checks} == {
        CheckName.DO_NOT_CONTACT,
        CheckName.CONSENT,
        CheckName.CALLING_HOURS,
        CheckName.CONTACT_CAP,
    }


@pytest.mark.parametrize(
    "action,perms",
    [
        (Action.CALL, ContactPermissions(sms=True, email=True, push=True)),
        (Action.PAYMENT_PLAN, ContactPermissions(sms=True, email=True, push=True)),
        (Action.SMS_PAYMENT_LINK, ContactPermissions(call=True, email=True, push=True)),
        (Action.EMAIL, ContactPermissions(call=True, sms=True, push=True)),
        (Action.PUSH, ContactPermissions(call=True, sms=True, email=True)),
    ],
)
def test_missing_channel_consent_drops_action(
    make_ctx: Ctx, action: Action, perms: ContactPermissions
) -> None:
    r = permission_gate(make_ctx(contact_permissions=perms), action)
    assert not r.allowed
    assert [c.check for c in r.checks if not c.passed] == [CheckName.CONSENT]


def test_do_not_contact_drops_every_contact(make_ctx: Ctx) -> None:
    ctx = make_ctx(do_not_contact=True)
    assert all(not permission_gate(ctx, a).allowed for a in CONTACT_ACTIONS)


@pytest.mark.parametrize("n,allowed", [(0, True), (2, True), (3, False), (7, False)])
def test_seven_day_cap(make_ctx: Ctx, n: int, allowed: bool) -> None:
    r = permission_gate(make_ctx(contacts_last_7d=n), Action.CALL)
    assert r.allowed is allowed
    cap = next(c for c in r.checks if c.check is CheckName.CONTACT_CAP)
    assert f"{n} of 3" in cap.detail


@pytest.mark.parametrize(
    "utc,tz,allowed",
    [
        # Toronto, EDT (UTC-4)
        (datetime(2026, 10, 2, 10, 59, tzinfo=UTC), "America/Toronto", False),  # 06:59
        (datetime(2026, 10, 2, 11, 0, tzinfo=UTC), "America/Toronto", True),  # 07:00
        (datetime(2026, 10, 3, 0, 59, tzinfo=UTC), "America/Toronto", True),  # 20:59
        (datetime(2026, 10, 3, 1, 0, tzinfo=UTC), "America/Toronto", False),  # 21:00
        # Vancouver, PDT (UTC-7): 22:00 UTC = 15:00
        (datetime(2026, 10, 2, 22, 0, tzinfo=UTC), "America/Vancouver", True),
        # Vancouver: 04:30 UTC = 21:30 previous day
        (datetime(2026, 10, 3, 4, 30, tzinfo=UTC), "America/Vancouver", False),
        # St. John's, NDT (UTC-2:30): 09:29 UTC = 06:59, 09:30 UTC = 07:00
        (datetime(2026, 10, 2, 9, 29, tzinfo=UTC), "America/St_Johns", False),
        (datetime(2026, 10, 2, 9, 30, tzinfo=UTC), "America/St_Johns", True),
        # DST fall-back, 1 Nov 2026: 11:30 UTC is 06:30 EST (would be 07:30 if we forgot DST)
        (datetime(2026, 11, 1, 11, 30, tzinfo=UTC), "America/Toronto", False),
        (datetime(2026, 11, 1, 12, 0, tzinfo=UTC), "America/Toronto", True),
        # Regina has no DST (UTC-6 all year): 12:59 UTC = 06:59
        (datetime(2026, 7, 1, 12, 59, tzinfo=UTC), "America/Regina", False),
    ],
)
def test_local_calling_hours(make_ctx: Ctx, utc: datetime, tz: str, allowed: bool) -> None:
    r = permission_gate(make_ctx(now=utc, time_zone=tz), Action.CALL)
    hours = next(c for c in r.checks if c.check is CheckName.CALLING_HOURS)
    assert hours.passed is allowed


def test_customer_specific_window(make_ctx: Ctx) -> None:
    from datetime import time

    # 18:00 Toronto is fine by default but outside a 09:00-17:00 customer window
    r = permission_gate(
        make_ctx(permitted_call_start_local=time(9), permitted_call_end_local=time(17)), Action.CALL
    )
    assert not r.allowed and [c.check for c in r.checks if not c.passed] == [CheckName.CALLING_HOURS]


def test_window_must_be_ordered(make_ctx: Ctx) -> None:
    from datetime import time

    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        make_ctx(permitted_call_start_local=time(21), permitted_call_end_local=time(7))


@pytest.mark.parametrize("sunday_ok,allowed", [(False, False), (True, True)])
def test_sunday_contact(make_ctx: Ctx, sunday_ok: bool, allowed: bool) -> None:
    sunday_noon = datetime(2026, 10, 4, 16, 0, tzinfo=UTC)  # Sun 4 Oct 2026, 12:00 Toronto
    r = permission_gate(
        make_ctx(now=sunday_noon, sunday_contact_permitted=sunday_ok), Action.SMS_PAYMENT_LINK
    )
    assert r.allowed is allowed


def test_sunday_is_judged_in_customer_local_time(make_ctx: Ctx) -> None:
    # 03:30 UTC Monday 5 Oct = 20:30 Sunday 4 Oct in Vancouver
    r = permission_gate(
        make_ctx(now=datetime(2026, 10, 5, 3, 30, tzinfo=UTC), time_zone="America/Vancouver"), Action.CALL
    )
    assert not r.allowed


@pytest.mark.parametrize("cap,n,allowed", [(2, 1, True), (2, 2, False), (5, 4, True), (0, 0, False)])
def test_per_case_cap(make_ctx: Ctx, cap: int, n: int, allowed: bool) -> None:
    r = permission_gate(make_ctx(contact_cap_7d=cap, contacts_last_7d=n), Action.CALL)
    assert r.allowed is allowed
    assert f"{n} of {cap}" in next(c for c in r.checks if c.check is CheckName.CONTACT_CAP).detail


@pytest.mark.parametrize("tz", ["", "Mars/Olympus_Mons", "EST5EDT-garbage"])
def test_unknown_time_zone_fails_closed(make_ctx: Ctx, tz: str) -> None:
    assert not permission_gate(make_ctx(time_zone=tz), Action.CALL).allowed


@given(st.integers(min_value=0, max_value=20), st.booleans(), st.booleans())
def test_gate_never_allows_what_any_check_denies(contacts: int, dnc: bool, call_ok: bool) -> None:
    from datetime import timedelta
    from decimal import Decimal

    ctx = CaseContext(
        case_id="C-1",
        golden_customer_id="G-000001",
        assigned_agent_id="a",
        now=datetime(2026, 10, 2, 22, 0, tzinfo=UTC),
        time_zone="America/Toronto",
        contact_permissions=ContactPermissions(call=call_ok),
        do_not_contact=dnc,
        contacts_last_7d=contacts,
        hardship_status=HardshipStatus.NONE,
        balance_at_risk=Decimal("1.00"),
        features_as_of=datetime(2026, 10, 2, 6, 0, tzinfo=UTC) - timedelta(hours=1),
    )
    r = permission_gate(ctx, Action.CALL)
    assert r.allowed == (contacts < 3 and not dnc and call_ok)


def test_allowed_actions_keeps_wait(make_ctx: Ctx) -> None:
    ctx = make_ctx(do_not_contact=True)
    actions, results = allowed_actions(ctx)
    assert actions == [Action.WAIT]
    assert len(results) == len(Action)


# ----------------------------------------------------------------- hardship override
@pytest.mark.parametrize("status", [HardshipStatus.POSSIBLE, HardshipStatus.CONFIRMED])
def test_hardship_limits_to_protective_actions(make_ctx: Ctx, status: HardshipStatus) -> None:
    out = hardship_override(make_ctx(hardship_status=status), list(Action))
    assert set(out) == set(HARDSHIP_ALLOWED_ACTIONS)
    assert Action.SMS_PAYMENT_LINK not in out and Action.PROMISE_REQUEST not in out


def test_vulnerability_protects_like_hardship(make_ctx: Ctx) -> None:
    out = hardship_override(make_ctx(vulnerable=True), list(Action))
    assert set(out) == set(HARDSHIP_ALLOWED_ACTIONS)


def test_no_hardship_unchanged_and_order_preserved(make_ctx: Ctx) -> None:
    order = [Action.SMS_PAYMENT_LINK, Action.CALL, Action.WAIT]
    assert hardship_override(make_ctx(), order) == order
    assert hardship_override(make_ctx(hardship_status=HardshipStatus.POSSIBLE), order) == [
        Action.CALL,
        Action.WAIT,
    ]


@given(st.lists(st.sampled_from(list(Action)), unique=True))
def test_hardship_override_only_removes(actions: list[Action]) -> None:
    from datetime import timedelta
    from decimal import Decimal

    ctx = CaseContext(
        case_id="C-1",
        golden_customer_id="G-000001",
        assigned_agent_id="a",
        now=datetime(2026, 10, 2, 22, 0, tzinfo=UTC),
        time_zone="America/Toronto",
        contact_permissions=ContactPermissions(),
        do_not_contact=False,
        contacts_last_7d=0,
        hardship_status=HardshipStatus.POSSIBLE,
        balance_at_risk=Decimal("1.00"),
        features_as_of=datetime(2026, 10, 2, 6, 0, tzinfo=UTC) - timedelta(hours=1),
    )
    out = hardship_override(ctx, actions)
    assert set(out) <= set(actions) and set(out) <= HARDSHIP_ALLOWED_ACTIONS
