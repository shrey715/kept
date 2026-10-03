"""The NBA card end to end, with fakes for context, features and the uplift model."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from kept.config import PROPOSAL_TTL
from kept.contracts import (
    HARDSHIP_ALLOWED_ACTIONS,
    Action,
    AuditKind,
    CaseContext,
    FeatureVector,
    HardshipStatus,
    HardStop,
    ReleaseTier,
)
from kept.nba.engine import KeptEngine

from ..fakes import ConstantScorer, FixedContextBuilder, InMemoryAuditLog, StaticFeatureProvider

NOW = datetime(2026, 10, 2, 22, 0, tzinfo=UTC)
PROBS = {
    "wait": 0.22,
    "email": 0.25,
    "push": 0.23,
    "sms_payment_link": 0.30,
    "call": 0.58,
    "promise_request": 0.40,
    "payment_plan": 0.50,
    "hardship_review": 0.47,
}


@pytest.fixture
def engine(make_ctx: Callable[..., CaseContext]):  # type: ignore[no-untyped-def]
    def _engine(
        *, kill_switch: bool = False, error: Exception | None = None, **ctx_over: Any
    ) -> tuple[KeptEngine, InMemoryAuditLog]:
        ctx = make_ctx(**ctx_over)
        fv = FeatureVector(
            case_id=ctx.case_id,
            golden_customer_id=ctx.golden_customer_id,
            as_of=ctx.features_as_of,
            feature_set_version="fs-0",
            max_dpd=18,
            days_to_next_payroll=0,
        )
        log = InMemoryAuditLog()
        eng = KeptEngine(
            context=FixedContextBuilder({ctx.case_id: ctx}),
            features=StaticFeatureProvider({ctx.case_id: fv}, error=error),
            scorer=ConstantScorer(PROBS, model_version="nba-0.3"),
            audit_log=log,
            kill_switch=kill_switch,
        )
        return eng, log

    return _engine


def test_normal_case_recommends_best_allowed_action(engine) -> None:  # type: ignore[no-untyped-def]
    eng, log = engine()
    card = eng.recommend("C-118204", NOW)
    assert card.proposal is not None and card.proposal.action is Action.CALL
    assert card.proposal.tier is ReleaseTier.AMBER
    assert card.proposal.expires_at - card.proposal.created_at == PROPOSAL_TTL
    assert card.model_version == "nba-0.3" and card.features_as_of == card.proposal.features_as_of
    assert card.probabilities[0].action is Action.CALL
    assert any(p.action is Action.WAIT for p in card.probabilities)
    assert len(card.reasons) <= 3 and card.checks
    assert len(log.read(kind=AuditKind.RECOMMENDATION)) == 1


def test_window_is_inside_local_calling_hours(engine) -> None:  # type: ignore[no-untyped-def]
    from zoneinfo import ZoneInfo

    eng, _ = engine()
    p = eng.recommend("C-118204", NOW).proposal
    assert p is not None and p.window_start and p.window_end
    tz = ZoneInfo("America/Toronto")
    assert p.window_start.astimezone(tz).hour >= 7 and p.window_end.astimezone(tz).hour <= 21


def test_hard_stop_means_no_action_and_shows_rule(engine) -> None:  # type: ignore[no-untyped-def]
    eng, _ = engine(hard_stop_flags=frozenset({HardStop.DECEASED}))
    card = eng.recommend("C-118204", NOW)
    assert card.proposal is None and card.hard_stop is not None and card.hard_stop.blocked
    assert card.no_action_reason


def test_hardship_restricts_and_goes_red(engine) -> None:  # type: ignore[no-untyped-def]
    eng, _ = engine(hardship_status=HardshipStatus.POSSIBLE)
    card = eng.recommend("C-118204", NOW)
    assert card.proposal is not None and card.proposal.action in HARDSHIP_ALLOWED_ACTIONS
    assert card.proposal.tier is ReleaseTier.RED
    assert card.hardship_banner
    assert all(p.action in HARDSHIP_ALLOWED_ACTIONS for p in card.probabilities)


def test_stale_features_mean_no_action(engine) -> None:  # type: ignore[no-untyped-def]
    eng, _ = engine(features_as_of=NOW - timedelta(hours=30))
    card = eng.recommend("C-118204", NOW)
    assert card.proposal is None and "stale" in (card.no_action_reason or "").lower()


def test_errors_mean_no_action_not_an_exception(engine) -> None:  # type: ignore[no-untyped-def]
    eng, log = engine(error=RuntimeError("feature store down"))
    card = eng.recommend("C-118204", NOW)
    assert card.proposal is None and card.no_action_reason
    assert len(log.read(kind=AuditKind.RECOMMENDATION)) == 1


@pytest.mark.parametrize("kw", [{"kill_switch": True}, {"in_holdout": True}])
def test_kill_switch_and_holdout_use_legacy_strategy(engine, kw: dict[str, Any]) -> None:  # type: ignore[no-untyped-def]
    eng, _ = engine(legacy_action=Action.SMS_PAYMENT_LINK, **kw)
    card = eng.recommend("C-118204", NOW)
    assert card.proposal is not None and card.proposal.is_legacy_strategy
    assert card.proposal.action is Action.SMS_PAYMENT_LINK


def test_legacy_strategy_still_obeys_safety_rules(engine) -> None:  # type: ignore[no-untyped-def]
    eng, _ = engine(kill_switch=True, legacy_action=Action.CALL, hard_stop_flags=frozenset({HardStop.CEASE}))
    assert eng.recommend("C-118204", NOW).proposal is None


def test_no_consent_anywhere_recommends_wait_or_nothing(engine) -> None:  # type: ignore[no-untyped-def]
    from kept.contracts import ContactPermissions

    eng, _ = engine(contact_permissions=ContactPermissions())
    card = eng.recommend("C-118204", NOW)
    assert card.proposal is None or card.proposal.action is Action.WAIT


def test_unknown_case_raises_key_error(engine) -> None:  # type: ignore[no-untyped-def]
    eng, _ = engine()
    with pytest.raises(KeyError):
        eng.recommend("C-404", NOW)


@pytest.mark.perf
def test_card_latency_budget(engine) -> None:  # type: ignore[no-untyped-def]
    import time

    eng, _ = engine()
    eng.recommend("C-118204", NOW)
    start = time.perf_counter()
    for _ in range(20):
        eng.recommend("C-118204", NOW)
    assert (time.perf_counter() - start) / 20 < 0.300


def test_early_morning_batch_proposes_the_first_slot_of_the_day(engine) -> None:  # type: ignore[no-untyped-def]
    from zoneinfo import ZoneInfo

    early = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)  # 05:00 Toronto: outside hours right now
    eng, _ = engine(now=early, features_as_of=early - timedelta(hours=3))
    p = eng.recommend("C-118204", early).proposal
    assert p is not None and p.action is Action.CALL  # checked at the slot, not at 05:00
    assert p.window_start and p.window_start.astimezone(ZoneInfo("America/Toronto")).hour == 7


def test_vulnerable_customer_goes_red_and_protective(engine) -> None:  # type: ignore[no-untyped-def]
    eng, _ = engine(vulnerable=True)
    card = eng.recommend("C-118204", NOW)
    assert card.proposal is not None and card.proposal.tier is ReleaseTier.RED
    assert card.proposal.action in HARDSHIP_ALLOWED_ACTIONS and card.hardship_banner


def test_proposals_are_stored_for_the_release_gate(make_ctx) -> None:  # type: ignore[no-untyped-def]
    ctx = make_ctx()
    fv = FeatureVector(
        case_id=ctx.case_id,
        golden_customer_id=ctx.golden_customer_id,
        as_of=ctx.features_as_of,
        feature_set_version="fs-0",
    )
    store: dict[str, Any] = {}
    eng = KeptEngine(
        context=FixedContextBuilder({ctx.case_id: ctx}),
        features=StaticFeatureProvider({ctx.case_id: fv}),
        scorer=ConstantScorer(PROBS),
        audit_log=InMemoryAuditLog(),
        proposals=store,
    )
    p = eng.recommend(ctx.case_id, NOW).proposal
    assert p is not None and store == {p.proposal_id: p}


def test_new_recommendation_supersedes_the_pending_one(make_ctx) -> None:  # type: ignore[no-untyped-def]
    from kept.contracts.nba import ProposalStatus

    ctx = make_ctx()
    fv = FeatureVector(
        case_id=ctx.case_id,
        golden_customer_id=ctx.golden_customer_id,
        as_of=ctx.features_as_of,
        feature_set_version="fs-0",
    )
    store: dict[str, Any] = {}
    eng = KeptEngine(
        context=FixedContextBuilder({ctx.case_id: ctx}),
        features=StaticFeatureProvider({ctx.case_id: fv}),
        scorer=ConstantScorer(PROBS),
        audit_log=InMemoryAuditLog(),
        proposals=store,
    )
    a = eng.recommend(ctx.case_id, NOW).proposal
    b = eng.recommend(ctx.case_id, NOW).proposal
    assert a and b and store[a.proposal_id].status is ProposalStatus.CANCELLED
    assert store[b.proposal_id].status is ProposalStatus.PENDING


def test_window_starts_on_a_half_hour(engine) -> None:  # type: ignore[no-untyped-def]
    from zoneinfo import ZoneInfo

    t = datetime(2026, 10, 2, 18, 7, 30, tzinfo=UTC)  # 14:07:30 Toronto
    eng, _ = engine(now=t, features_as_of=t - timedelta(hours=3))
    p = eng.recommend("C-118204", t).proposal
    assert p is not None and p.window_start is not None
    local = p.window_start.astimezone(ZoneInfo("America/Toronto"))
    assert (local.hour, local.minute, local.second) == (14, 30, 0)
