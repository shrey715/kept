"""Human approval and the release gate. The model never sends anything itself."""

from __future__ import annotations

import random
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from kept.config import PROPOSAL_TTL
from kept.contracts import (
    Action,
    AuditKind,
    CaseContext,
    Channel,
    ContactPermissions,
    HardshipStatus,
    HardStop,
    Proposal,
    ProposalStatus,
    ReleaseDecision,
    ReleaseTier,
    ReviewDecision,
    Role,
)
from kept.nba.release import Releaser, cancel_pending, in_holdout, is_stale, sample_for_batch_review

from ..fakes import FixedContextBuilder, InMemoryAuditLog

T0 = datetime(2026, 10, 2, 22, 0, tzinfo=UTC)  # 18:00 Toronto
LATER = T0 + timedelta(hours=1)


# ----------------------------------------------------------------- hold-out
def test_holdout_is_deterministic_and_about_five_percent() -> None:
    ids = [f"G-{i:06d}" for i in range(20_000)]
    a = [in_holdout(g, salt="s1") for g in ids]
    assert a == [in_holdout(g, salt="s1") for g in ids]
    assert 0.045 <= sum(a) / len(a) <= 0.055


def test_holdout_depends_on_salt_and_is_order_independent() -> None:
    ids = [f"G-{i:06d}" for i in range(5_000)]
    assert [in_holdout(g, salt="s1") for g in ids] != [in_holdout(g, salt="s2") for g in ids]
    assert {g for g in ids if in_holdout(g, salt="s1")} == {
        g for g in reversed(ids) if in_holdout(g, salt="s1")
    }


# ----------------------------------------------------------------- batch sample
def _proposal(pid: str = "P-1", **kw: Any) -> Proposal:
    base: dict[str, Any] = dict(
        proposal_id=pid,
        case_id="C-118204",
        golden_customer_id="G-004817",
        action=Action.CALL,
        channel=Channel.CALL,
        tier=ReleaseTier.AMBER,
        model_version="nba-0.3",
        features_as_of=T0 - timedelta(hours=16),
        created_at=T0,
        expires_at=T0 + PROPOSAL_TTL,
    )
    base.update(kw)
    return Proposal(**base)


def test_batch_sample_twenty_unique() -> None:
    ps = [
        _proposal(f"P-{i}", tier=ReleaseTier.GREEN, action=Action.EMAIL, channel=Channel.EMAIL)
        for i in range(50)
    ]
    s = sample_for_batch_review(ps, rng=random.Random(0))
    assert len(s) == 20 and len({p.proposal_id for p in s}) == 20
    assert len(sample_for_batch_review(ps[:5], rng=random.Random(0))) == 5
    assert sample_for_batch_review(ps, rng=random.Random(1)) == sample_for_batch_review(
        ps, rng=random.Random(1)
    )


@pytest.mark.parametrize(
    "age,stale",
    [
        (timedelta(hours=16), False),
        (timedelta(hours=26), False),
        (timedelta(hours=26, seconds=1), True),
        (timedelta(hours=-1), True),
    ],
)
def test_staleness(age: timedelta, stale: bool) -> None:
    assert is_stale(T0 - age, now=T0) is stale


# ----------------------------------------------------------------- releaser
@pytest.fixture
def world(make_ctx: Callable[..., CaseContext]):  # type: ignore[no-untyped-def]
    def _world(
        proposal: Proposal | None = None, **ctx_over: Any
    ) -> tuple[Releaser, dict[str, Proposal], InMemoryAuditLog, FixedContextBuilder]:
        p = proposal or _proposal()
        proposals = {p.proposal_id: p}
        builder = FixedContextBuilder({p.case_id: make_ctx(**ctx_over)})
        log = InMemoryAuditLog()
        return Releaser(proposals=proposals, context=builder, audit_log=log), proposals, log, builder

    return _world


def _decide(**kw: Any) -> ReleaseDecision:
    base: dict[str, Any] = dict(
        proposal_id="P-1",
        reviewer_id="agent-7",
        reviewer_role=Role.AGENT,
        decision=ReviewDecision.ACCEPT,
        decided_at=LATER,
    )
    base.update(kw)
    return ReleaseDecision(**base)


def test_amber_released_by_assigned_agent(world) -> None:  # type: ignore[no-untyped-def]
    rel, proposals, log, _ = world()
    r = rel.release(_decide(), LATER)
    assert r.released and r.executed_at == LATER
    assert proposals["P-1"].status is ProposalStatus.RELEASED
    events = log.read(subject_id="P-1")
    assert len(events) == 1 and events[0].kind is AuditKind.RELEASE and r.audit_event_id == events[0].event_id


@pytest.mark.parametrize(
    "kw",
    [
        {"reviewer_id": "agent-8"},  # not the assigned agent
        {"reviewer_role": Role.ANALYST, "reviewer_id": "agent-7"},
    ],
)
def test_amber_wrong_reviewer(world, kw: dict[str, Any]) -> None:  # type: ignore[no-untyped-def]
    rel, proposals, log, _ = world()
    r = rel.release(_decide(**kw), LATER)
    assert not r.released and proposals["P-1"].status is ProposalStatus.PENDING
    assert len(log.read(subject_id="P-1")) == 1


def test_expired_approval(world) -> None:  # type: ignore[no-untyped-def]
    rel, _, _, _ = world()
    at = T0 + PROPOSAL_TTL
    r = rel.release(_decide(decided_at=at), at)
    assert not r.released and "expire" in r.reason.lower()


@pytest.mark.parametrize(
    "ctx_over,word",
    [
        ({"contact_permissions": ContactPermissions(sms=True, email=True)}, "consent"),
        ({"hard_stop_flags": frozenset({HardStop.CEASE})}, "cease"),
        ({"do_not_contact": True}, "contact"),
        ({"contacts_last_7d": 3}, "cap"),
    ],
)
def test_recheck_on_fresh_data(world, ctx_over: dict[str, Any], word: str) -> None:  # type: ignore[no-untyped-def]
    rel, proposals, log, _ = world(**ctx_over)
    r = rel.release(_decide(), LATER)
    assert not r.released and word in r.reason.lower()
    assert proposals["P-1"].status is ProposalStatus.PENDING
    assert len(log.read(subject_id="P-1")) == 1


def test_outside_calling_hours_at_release_time(world) -> None:  # type: ignore[no-untyped-def]
    rel, _, _, _ = world()
    late = datetime(2026, 10, 3, 1, 30, tzinfo=UTC)  # 21:30 Toronto, still before expiry
    r = rel.release(_decide(decided_at=late), late)
    assert not r.released


def test_context_error_means_no_action_but_still_logged(world) -> None:  # type: ignore[no-untyped-def]
    rel, _, log, builder = world()
    builder.error = RuntimeError("warehouse unavailable")
    r = rel.release(_decide(), LATER)
    assert not r.released and len(log.read(subject_id="P-1")) == 1


def test_red_needs_specialist_and_a_second_person(world) -> None:  # type: ignore[no-untyped-def]
    red = _proposal(tier=ReleaseTier.RED, action=Action.HARDSHIP_REVIEW)
    rel, _, _, _ = world(red)
    assert not rel.release(
        _decide(reviewer_id="hs-1", reviewer_role=Role.HARDSHIP_SPECIALIST), LATER
    ).released
    rel, _, _, _ = world(red)
    assert not rel.release(
        _decide(
            reviewer_id="agent-7",
            reviewer_role=Role.AGENT,
            second_reviewer_id="tl-1",
            second_reviewer_role=Role.TEAM_LEAD,
        ),
        LATER,
    ).released
    rel, _, _, _ = world(red)
    ok = rel.release(
        _decide(
            reviewer_id="hs-1",
            reviewer_role=Role.HARDSHIP_SPECIALIST,
            second_reviewer_id="tl-1",
            second_reviewer_role=Role.TEAM_LEAD,
        ),
        LATER,
    )
    assert ok.released


def test_green_released_by_team_lead(world) -> None:  # type: ignore[no-untyped-def]
    green = _proposal(tier=ReleaseTier.GREEN, action=Action.SMS_PAYMENT_LINK, channel=Channel.SMS)
    rel, _, _, _ = world(green)
    assert rel.release(_decide(reviewer_id="tl-1", reviewer_role=Role.TEAM_LEAD), LATER).released
    rel, _, _, _ = world(green)
    assert not rel.release(_decide(), LATER).released  # agent can't release the green batch


@pytest.mark.parametrize("role", list(Role))
def test_blocked_never_released(world, role: Role) -> None:  # type: ignore[no-untyped-def]
    rel, _, _, _ = world(_proposal(tier=ReleaseTier.BLOCKED, action=Action.WAIT, channel=None))
    assert not rel.release(_decide(reviewer_id="x", reviewer_role=role), LATER).released


def test_override_logged_as_override(world) -> None:  # type: ignore[no-untyped-def]
    rel, _, log, _ = world()
    rel.release(_decide(decision=ReviewDecision.OVERRIDE, override_reason="customer asked for email"), LATER)
    assert [e.kind for e in log.read(subject_id="P-1")] == [AuditKind.OVERRIDE]


def test_double_release_refused(world) -> None:  # type: ignore[no-untyped-def]
    rel, _, log, _ = world()
    assert rel.release(_decide(), LATER).released
    assert not rel.release(_decide(), LATER + timedelta(minutes=1)).released
    assert len(log.read(subject_id="P-1")) == 2


def test_unknown_proposal(world) -> None:  # type: ignore[no-untyped-def]
    rel, _, log, _ = world()
    r = rel.release(_decide(proposal_id="P-404"), LATER)
    assert not r.released and len(log.read(subject_id="P-404")) == 1


# ----------------------------------------------------------------- cancellation
def test_payment_or_cease_cancels_pending() -> None:
    proposals = {
        "P-1": _proposal("P-1"),
        "P-2": _proposal("P-2", status=ProposalStatus.RELEASED),
        "P-3": _proposal("P-3", case_id="C-OTHER"),
    }
    log = InMemoryAuditLog()
    out = cancel_pending("C-118204", reason="payment received", proposals=proposals, audit_log=log, now=LATER)
    assert out == ["P-1"]
    assert proposals["P-1"].status is ProposalStatus.CANCELLED
    assert (
        proposals["P-2"].status is ProposalStatus.RELEASED
        and proposals["P-3"].status is ProposalStatus.PENDING
    )
    assert [e.kind for e in log.read()] == [AuditKind.PROPOSAL_CANCELLED]


# ----------------------------------------------------------------- edits, alternatives, reject
def _sized(amount: str = "140.00") -> Proposal:
    from datetime import date
    from decimal import Decimal

    from kept.contracts.nba import PromiseSizing

    sizing = PromiseSizing(
        amount=Decimal(amount),
        due_date=date(2026, 10, 3),
        installments=3,
        spare_cash_estimate=Decimal("160.00"),
        payday=date(2026, 10, 2),
        rationale="r",
    )
    return _proposal(action=Action.PAYMENT_PLAN, sizing=sizing)


def test_edit_must_stay_within_spare_cash(world) -> None:  # type: ignore[no-untyped-def]
    from decimal import Decimal

    rel, proposals, _, _ = world(_sized())
    assert not rel.release(
        _decide(decision=ReviewDecision.EDIT, edited_amount=Decimal("200.00")), LATER
    ).released
    ok = rel.release(_decide(decision=ReviewDecision.EDIT, edited_amount=Decimal("150.00")), LATER)
    assert ok.released and proposals["P-1"].sizing.amount == Decimal("150.00")


def test_hardship_since_the_proposal_raises_the_tier(world) -> None:  # type: ignore[no-untyped-def]
    rel, proposals, _, _ = world(hardship_status=HardshipStatus.POSSIBLE)
    r = rel.release(_decide(), LATER)  # Amber call, but hardship now applies: Red, agent can't
    assert not r.released and proposals["P-1"].status is ProposalStatus.PENDING


def test_alternative_is_rechecked_and_released(world) -> None:  # type: ignore[no-untyped-def]
    rel, proposals, _, _ = world()
    r = rel.release(
        _decide(decision=ReviewDecision.ALTERNATIVE, alternative_action=Action.SMS_PAYMENT_LINK), LATER
    )
    assert (
        r.released
        and proposals["P-1"].action is Action.SMS_PAYMENT_LINK
        and proposals["P-1"].channel is Channel.SMS
    )


def test_reject(world) -> None:  # type: ignore[no-untyped-def]
    rel, proposals, log, _ = world()
    r = rel.release(_decide(decision=ReviewDecision.REJECT), LATER)
    assert not r.released and proposals["P-1"].status is ProposalStatus.REJECTED and len(log.read()) == 1


# ----------------------------------------------------------------- Red in two steps
def test_red_two_step_handoff(world) -> None:  # type: ignore[no-untyped-def]
    red = _proposal(tier=ReleaseTier.RED, action=Action.HARDSHIP_REVIEW)
    rel, proposals, log, _ = world(red)
    first = rel.release(_decide(reviewer_id="hs-1", reviewer_role=Role.HARDSHIP_SPECIALIST), LATER)
    assert not first.released and proposals["P-1"].status is ProposalStatus.APPROVED
    assert rel.first_approver("P-1") == ("hs-1", Role.HARDSHIP_SPECIALIST)
    same = rel.release(_decide(reviewer_id="hs-1", reviewer_role=Role.HARDSHIP_SPECIALIST), LATER)
    assert not same.released and "different person" in same.reason
    agent = rel.release(_decide(reviewer_id="agent-9", reviewer_role=Role.AGENT), LATER)
    assert not agent.released and proposals["P-1"].status is ProposalStatus.APPROVED
    done = rel.release(_decide(reviewer_id="tl-1", reviewer_role=Role.TEAM_LEAD), LATER)
    assert done.released and proposals["P-1"].status is ProposalStatus.RELEASED
    assert rel.first_approver("P-1") is None
    assert len(log.read(subject_id="P-1")) == 4


def test_red_second_step_rechecks_fresh_data(world) -> None:  # type: ignore[no-untyped-def]
    red = _proposal(tier=ReleaseTier.RED, action=Action.HARDSHIP_REVIEW)
    rel, proposals, _, builder = world(red)
    rel.release(_decide(reviewer_id="hs-1", reviewer_role=Role.HARDSHIP_SPECIALIST), LATER)
    ctx = builder.contexts["C-118204"]
    builder.contexts["C-118204"] = ctx.model_copy(update={"hard_stop_flags": frozenset({HardStop.CEASE})})
    r = rel.release(_decide(reviewer_id="tl-1", reviewer_role=Role.TEAM_LEAD), LATER)
    assert not r.released and "cease" in r.reason.lower()
    assert proposals["P-1"].status is ProposalStatus.APPROVED


def test_red_second_step_can_reject(world) -> None:  # type: ignore[no-untyped-def]
    red = _proposal(tier=ReleaseTier.RED, action=Action.HARDSHIP_REVIEW)
    rel, proposals, _, _ = world(red)
    rel.release(_decide(reviewer_id="hs-1", reviewer_role=Role.HARDSHIP_SPECIALIST), LATER)
    rel.release(
        _decide(reviewer_id="tl-1", reviewer_role=Role.TEAM_LEAD, decision=ReviewDecision.REJECT), LATER
    )
    assert proposals["P-1"].status is ProposalStatus.REJECTED
