"""The NBA card end to end, with fakes for context, features and the uplift model."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pandas as pd
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
from kept.nba.engine import KeptEngine, _legacy_text

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


def test_a_cease_that_lands_cancels_the_pending_proposal(make_ctx) -> None:  # type: ignore[no-untyped-def]
    from kept.contracts.enums import HardStop
    from kept.contracts.nba import ProposalStatus

    ctx = make_ctx()
    fv = FeatureVector(
        case_id=ctx.case_id,
        golden_customer_id=ctx.golden_customer_id,
        as_of=ctx.features_as_of,
        feature_set_version="fs-0",
    )
    cases = {ctx.case_id: ctx}
    store: dict[str, Any] = {}
    log = InMemoryAuditLog()
    eng = KeptEngine(
        context=FixedContextBuilder(cases),
        features=StaticFeatureProvider({ctx.case_id: fv}),
        scorer=ConstantScorer(PROBS),
        audit_log=log,
        proposals=store,
    )
    a = eng.recommend(ctx.case_id, NOW).proposal
    cases[ctx.case_id] = ctx.model_copy(update={"hard_stop_flags": frozenset({HardStop.CEASE})})
    card = eng.recommend(ctx.case_id, NOW)
    assert a and card.proposal is None and store[a.proposal_id].status is ProposalStatus.CANCELLED
    cancelled = [e for e in log.read() if e.kind is AuditKind.PROPOSAL_CANCELLED]
    assert len(cancelled) == 1 and "cease" in cancelled[0].payload["reason"]


def test_window_starts_on_a_half_hour(engine) -> None:  # type: ignore[no-untyped-def]
    from zoneinfo import ZoneInfo

    t = datetime(2026, 10, 2, 18, 7, 30, tzinfo=UTC)  # 14:07:30 Toronto
    eng, _ = engine(now=t, features_as_of=t - timedelta(hours=3))
    p = eng.recommend("C-118204", t).proposal
    assert p is not None and p.window_start is not None
    local = p.window_start.astimezone(ZoneInfo("America/Toronto"))
    assert (local.hour, local.minute, local.second) == (14, 30, 0)


def _with_programs(make_ctx, programs):  # type: ignore[no-untyped-def]
    ctx = make_ctx(hardship_status=HardshipStatus.POSSIBLE)
    fv = FeatureVector(
        case_id=ctx.case_id,
        golden_customer_id=ctx.golden_customer_id,
        as_of=ctx.features_as_of,
        feature_set_version="fs-0",
    )
    return KeptEngine(
        context=FixedContextBuilder({ctx.case_id: ctx}),
        features=StaticFeatureProvider({ctx.case_id: fv}),
        scorer=ConstantScorer(PROBS),
        audit_log=InMemoryAuditLog(),
        programs=programs,
    ).recommend(ctx.case_id, NOW)


def test_banner_names_eligible_programmes(make_ctx) -> None:  # type: ignore[no-untyped-def]
    card = _with_programs(make_ctx, lambda ctx: ["3-month reduced payment (HP-LOAN-RED3 2026.1)"])
    assert card.hardship_banner and "Eligible programmes: 3-month reduced payment" in card.hardship_banner


def test_programmes_lookup_failure_keeps_the_card(make_ctx) -> None:  # type: ignore[no-untyped-def]
    def boom(ctx):  # type: ignore[no-untyped-def]
        raise NotImplementedError("Track C")

    card = _with_programs(make_ctx, boom)
    assert card.proposal is not None and card.hardship_banner and "Eligible" not in card.hardship_banner


@pytest.mark.parametrize(
    ("hardship", "want"),
    # the call becomes a payday-dated ask when one can be sized (#79): this balance needs instalments
    [(HardshipStatus.NONE, Action.PAYMENT_PLAN), (HardshipStatus.POSSIBLE, Action.HARDSHIP_REVIEW)],
)
def test_model_without_promise_plan_or_review_arms(make_ctx, hardship, want) -> None:  # type: ignore[no-untyped-def]
    """The real model only has the randomised arms: promise, plan and hardship review are calls and
    take the call's P(paid); hardship review only when hardship protects the case; a sizable call
    asks for a payday-dated promise."""
    ctx = make_ctx(hardship_status=hardship)
    fv = FeatureVector(
        case_id=ctx.case_id,
        golden_customer_id=ctx.golden_customer_id,
        as_of=ctx.features_as_of,
        feature_set_version="fs-0",
    )
    randomised = {a: PROBS[a] for a in ("wait", "email", "push", "sms_payment_link", "call")}
    eng = KeptEngine(
        context=FixedContextBuilder({ctx.case_id: ctx}),
        features=StaticFeatureProvider({ctx.case_id: fv}),
        scorer=ConstantScorer(randomised),
        audit_log=InMemoryAuditLog(),
    )
    card = eng.recommend(ctx.case_id, NOW)
    assert card.no_action_reason is None and card.proposal is not None
    assert card.proposal.action is want
    shown = {p.action for p in card.probabilities}
    assert (Action.HARDSHIP_REVIEW in shown) is (hardship is not HardshipStatus.NONE)


@pytest.mark.parametrize("hardship", [HardshipStatus.POSSIBLE, HardshipStatus.CONFIRMED])
def test_protected_case_is_offered_a_hardship_review_even_when_waiting_scores_best(
    make_ctx, hardship
) -> None:  # type: ignore[no-untyped-def]
    """A small balance where no contact beats waiting on money: an unprotected case waits, a
    protected one is offered the hardship review (Red), not "no action"."""
    flat = {a: 0.25 for a in ("wait", "email", "push", "sms_payment_link", "call")}

    def card(**over):  # type: ignore[no-untyped-def]
        ctx = make_ctx(balance_at_risk=Decimal("59.41"), **over)
        fv = FeatureVector(
            case_id=ctx.case_id,
            golden_customer_id=ctx.golden_customer_id,
            as_of=ctx.features_as_of,
            feature_set_version="fs-0",
        )
        eng = KeptEngine(
            context=FixedContextBuilder({ctx.case_id: ctx}),
            features=StaticFeatureProvider({ctx.case_id: fv}),
            scorer=ConstantScorer(flat),
            audit_log=InMemoryAuditLog(),
        )
        return eng.recommend(ctx.case_id, NOW)

    assert card().proposal is None
    protected = card(hardship_status=hardship)
    assert protected.proposal is not None and protected.proposal.action is Action.HARDSHIP_REVIEW
    assert protected.proposal.tier is ReleaseTier.RED
    # still no review when a hard stop blocks contact
    assert card(hardship_status=hardship, hard_stop_flags=frozenset({HardStop.CEASE})).proposal is None


def test_similar_cases_line(make_ctx) -> None:  # type: ignore[no-untyped-def]
    from kept.contracts.enums import Action
    from kept.nba.engine import similar_cases

    ctx = make_ctx()
    fv = FeatureVector(
        case_id=ctx.case_id,
        golden_customer_id=ctx.golden_customer_id,
        as_of=ctx.features_as_of,
        feature_set_version="fs-0",
        cohort_kept_rate=0.52,
        cohort_recovery_rate=0.64,
    )
    call = similar_cases(fv, Action.CALL)
    assert (
        call
        == "Similar past cases (same product and stage): 52% of their promises were kept and 64% recovered. (Descriptive, not causal.)"
    )
    plan = similar_cases(fv, Action.PAYMENT_PLAN)
    assert plan and "0-2 days after payday were kept 54%" in plan
    empty = fv.model_copy(update={"cohort_kept_rate": None, "cohort_recovery_rate": None})
    assert similar_cases(empty, Action.CALL) is None
    assert similar_cases(empty, Action.PROMISE_REQUEST) and "payday" in similar_cases(
        empty, Action.PROMISE_REQUEST
    )  # type: ignore[operator]


def test_card_compares_with_the_banks_current_strategy(engine) -> None:  # type: ignore[no-untyped-def]
    """Issue #90: one line with the legacy action and both chances of payment."""
    eng, _ = engine(legacy_action=Action.SMS_PAYMENT_LINK)
    card = eng.recommend("C-118204", NOW)
    assert card.proposal is not None and card.proposal.action is not Action.SMS_PAYMENT_LINK
    assert card.legacy_text is not None
    assert "text a payment link (30% chance" in card.legacy_text and card.legacy_text.endswith("%).")
    same, _ = engine(legacy_action=card.proposal.action)
    assert same.recommend("C-118204", NOW).legacy_text == "Same as the bank's current strategy."
    unscored = _legacy_text(
        Action.HARDSHIP_REVIEW,
        Action.EMAIL,
        pd.Series({"email": 0.29}),
        {Action.EMAIL: Action.EMAIL},
        [Action.EMAIL],
    )
    assert unscored == (
        "The bank's current strategy would: call to start a hardship review (our model doesn't score it for "
        "this customer, and it isn't allowed for this customer today). Ours: send a reminder email (29%)."
    )
    none, _ = engine(legacy_action=None)
    assert (
        none.recommend("C-118204", NOW).legacy_text
        == "The bank's current strategy has no action for this case."
    )


def test_drift_alarm_sends_green_cards_to_a_person(make_ctx) -> None:  # type: ignore[no-untyped-def]
    """#86: while a model input has drifted overnight, a Green proposal becomes Amber."""
    green = {"wait": 0.2, "email": 0.3, "push": 0.21, "sms_payment_link": 0.22, "call": 0.21}

    def tier(alarm):  # type: ignore[no-untyped-def]
        ctx = make_ctx()
        fv = FeatureVector(
            case_id=ctx.case_id,
            golden_customer_id=ctx.golden_customer_id,
            as_of=ctx.features_as_of,
            feature_set_version="fs-0",
        )
        eng = KeptEngine(
            context=FixedContextBuilder({ctx.case_id: ctx}),
            features=StaticFeatureProvider({ctx.case_id: fv}),
            scorer=ConstantScorer(green),
            audit_log=InMemoryAuditLog(),
            drift_alarm=alarm,
        )
        card = eng.recommend(ctx.case_id, NOW)
        assert card.proposal is not None and card.proposal.action is Action.EMAIL
        return card.proposal.tier

    assert tier(()) is ReleaseTier.GREEN
    assert tier(("max_dpd",)) is ReleaseTier.AMBER


def test_a_call_asks_for_a_payday_promise_only_when_one_can_be_sized(make_ctx) -> None:  # type: ignore[no-untyped-def]
    """#79: same contact, a sized ask. Without payday or spare cash it stays a plain call."""
    randomised = {a: PROBS[a] for a in ("wait", "email", "push", "sms_payment_link", "call")}

    def card(**over):  # type: ignore[no-untyped-def]
        ctx = make_ctx(**over)
        fv = FeatureVector(
            case_id=ctx.case_id,
            golden_customer_id=ctx.golden_customer_id,
            as_of=ctx.features_as_of,
            feature_set_version="fs-0",
        )
        eng = KeptEngine(
            context=FixedContextBuilder({ctx.case_id: ctx}),
            features=StaticFeatureProvider({ctx.case_id: fv}),
            scorer=ConstantScorer(randomised),
            audit_log=InMemoryAuditLog(),
        )
        return eng.recommend(ctx.case_id, NOW)

    sized = card()
    assert sized.proposal is not None and sized.proposal.action in (
        Action.PROMISE_REQUEST,
        Action.PAYMENT_PLAN,
    )
    assert sized.proposal.sizing is not None and sized.sizing_text
    plain = card(expected_next_payroll_date=None)
    assert (
        plain.proposal is not None and plain.proposal.action is Action.CALL and plain.proposal.sizing is None
    )
