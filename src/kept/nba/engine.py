"""Runs stages 1-7 and builds the NBA card. Implements NBAEngine."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd

from kept.common.audit import new_event_id
from kept.config import CLOSE_CALL_MARGIN, PROPOSAL_TTL
from kept.contracts.audit import AuditEvent, AuditKind
from kept.contracts.enums import ACTION_CHANNEL, Action, HardshipStatus
from kept.contracts.feature_registry import model_inputs
from kept.contracts.features import FeatureVector
from kept.contracts.interfaces import AuditLog, CaseContextBuilder, FeatureProvider, UpliftScorer
from kept.contracts.nba import (
    ActionScore,
    Alternative,
    CaseContext,
    CheckResult,
    NBACard,
    PromiseSizing,
    Proposal,
)
from kept.nba.explain import top_reasons
from kept.nba.ranking import is_close_call, score_actions
from kept.nba.release import is_stale
from kept.nba.rules import allowed_actions, hard_stops, hardship_override
from kept.nba.sizing import size_promise
from kept.nba.tiers import assign_tier

# Tuning knobs (CAD). Cost from contact_history.contact_cost_cad (call 2.40 in the dictionary);
# burden is what a contact costs the customer, so heavier channels weigh more. TBC on real data.
DEFAULT_CONTACT_COST: Mapping[Action, Decimal] = {
    Action.CALL: Decimal("2.40"),
    Action.PROMISE_REQUEST: Decimal("2.40"),
    Action.PAYMENT_PLAN: Decimal("2.40"),
    Action.HARDSHIP_REVIEW: Decimal("2.40"),
    Action.SMS_PAYMENT_LINK: Decimal("0.10"),
    Action.EMAIL: Decimal("0.01"),
    Action.PUSH: Decimal("0.01"),
}
DEFAULT_BURDEN: Mapping[Action, Decimal] = {
    Action.CALL: Decimal("2.00"),
    Action.PROMISE_REQUEST: Decimal("2.00"),
    Action.PAYMENT_PLAN: Decimal("2.00"),
    Action.HARDSHIP_REVIEW: Decimal("1.00"),
    Action.SMS_PAYMENT_LINK: Decimal("0.50"),
    Action.EMAIL: Decimal("0.25"),
    Action.PUSH: Decimal("0.25"),
}
WINDOW = timedelta(hours=2)
_SIZED = (Action.PROMISE_REQUEST, Action.PAYMENT_PLAN)
_LABEL = {
    Action.WAIT: "Wait",
    Action.EMAIL: "Send a reminder email",
    Action.PUSH: "Send an app reminder",
    Action.SMS_PAYMENT_LINK: "Text a payment link",
    Action.CALL: "Call",
    Action.PROMISE_REQUEST: "Call and ask for a payday-dated promise",
    Action.PAYMENT_PLAN: "Call and offer a payment plan",
    Action.HARDSHIP_REVIEW: "Call to start a hardship review",
}


def next_window(ctx: CaseContext, *, length: timedelta = WINDOW) -> tuple[datetime, datetime] | None:
    """The next contact slot from ctx.now inside the customer's own calling hours (local,
    DST-aware, Sundays only if permitted), as UTC. None if the time zone is unknown."""
    try:
        tz = ZoneInfo(ctx.time_zone)
    except (ZoneInfoNotFoundError, ValueError):
        return None
    local = ctx.now.astimezone(tz)
    for d in range(8):
        day = local.date() + timedelta(days=d)
        if day.weekday() == 6 and not ctx.sunday_contact_permitted:
            continue
        start = datetime.combine(day, ctx.permitted_call_start_local, tz)
        end = datetime.combine(day, ctx.permitted_call_end_local, tz)
        s = max(start, local)
        if s < end:
            return s.astimezone(UTC), min(s + length, end).astimezone(UTC)
    return None


class KeptEngine:
    def __init__(
        self,
        *,
        context: CaseContextBuilder,
        features: FeatureProvider,
        scorer: UpliftScorer,
        audit_log: AuditLog,
        kill_switch: bool = False,
        proposals: dict[str, Proposal] | None = None,
        contact_cost: Mapping[Action, Decimal] = DEFAULT_CONTACT_COST,
        burden: Mapping[Action, Decimal] = DEFAULT_BURDEN,
    ) -> None:
        """proposals: where new proposals are stored for the release gate (Releaser reads it)."""
        self._context = context
        self._features = features
        self._scorer = scorer
        self._log = audit_log
        self._kill_switch = kill_switch
        self._proposals = proposals if proposals is not None else {}
        self._cost = contact_cost
        self._burden = burden

    def recommend(self, case_id: str, now: datetime) -> NBACard:
        """An unknown case (KeyError from the context builder) propagates. After that it never
        raises: feature/model errors and stale features return a card with proposal None and
        no_action_reason set. Hard stops and the permission gate apply to every proposal,
        including legacy ones. Call windows lie inside customer-local calling hours.
        Hold-out cases and the kill switch return the legacy action
        (legacy.legacy_to_action(nba_recommendation_last), is_legacy_strategy True).
        The hardship banner names eligible programmes (hardship.programs), e.g.
        "HP-REDUCE v2 eligible". Logs one RECOMMENDATION audit event."""
        ctx = self._context.build(case_id, now)
        try:
            card = self._card(ctx)
        except Exception as e:  # never raise after the context: no action, and say why
            card = self._no_action(ctx, f"No action: the recommendation failed ({type(e).__name__}).")
        if card.proposal is not None:
            self._proposals[card.proposal.proposal_id] = card.proposal
        self._log.append(
            AuditEvent(
                event_id=new_event_id(),
                at=now,
                kind=AuditKind.RECOMMENDATION,
                actor_id="system:nba",
                subject_id=case_id,
                payload={
                    "proposal_id": card.proposal.proposal_id if card.proposal else None,
                    "action": card.proposal.action.value if card.proposal else None,
                    "tier": card.proposal.tier.value if card.proposal else None,
                    "is_legacy_strategy": card.proposal.is_legacy_strategy if card.proposal else False,
                    "model_version": card.model_version,
                    "features_as_of": card.features_as_of.isoformat(),
                    "no_action_reason": card.no_action_reason,
                    "hard_stops": [h.value for h in card.hard_stop.fired] if card.hard_stop else [],
                },
            )
        )
        return card

    # ------------------------------------------------------------------ stages
    def _card(self, ctx: CaseContext) -> NBACard:
        stop = hard_stops(ctx)  # stage 1
        if stop.blocked:
            return self._no_action(ctx, stop.rule_card or "Hard stop.", hard_stop=stop)
        if is_stale(ctx.features_as_of, now=ctx.now):
            return self._no_action(
                ctx, f"No action: features are stale (as of {ctx.features_as_of:%Y-%m-%d %H:%M} UTC)."
            )

        slot = next_window(ctx)
        gate_ctx = ctx.model_copy(update={"now": slot[0]}) if slot else ctx  # check at the slot we propose
        allowed, results = allowed_actions(gate_ctx)  # stage 2
        allowed = hardship_override(ctx, allowed)  # stage 3
        checks = {r.action: r.checks for r in results}

        if self._kill_switch or ctx.in_holdout:
            return self._legacy(ctx, allowed, checks, slot)

        fv = self._features.get_online(ctx.case_id)
        X = _model_frame(fv)
        proba = self._scorer.predict_proba(X).iloc[0]  # stage 4
        p_paid = {a: float(proba[a.value]) for a in allowed}

        sizing = _sizing(ctx)  # stage 5
        if sizing is None:
            p_paid = {a: p for a, p in p_paid.items() if a not in _SIZED}

        ranked = score_actions(  # stage 6
            p_paid=p_paid, balance_at_risk=ctx.balance_at_risk, contact_cost=self._cost, burden=self._burden
        )
        best = ranked[0]
        probs = _alternatives(best.action, ranked)
        if best.action is Action.WAIT:
            return self._no_action(
                ctx, "Best action is to wait: no contact beats waiting today.", probabilities=probs
            )

        reasons = []  # stage 7
        explain = getattr(self._scorer, "contributions", None)
        if explain is not None:
            values = fv.model_dump()
            reasons = top_reasons(explain(X, best.action), values)
        tier = assign_tier(
            action=best.action,
            hard_stopped=False,
            hardship_status=_protective_status(ctx),
            close_call=is_close_call(ranked, margin=CLOSE_CALL_MARGIN),
        )
        proposal = self._proposal(ctx, best.action, tier, slot, sizing if best.action in _SIZED else None)
        return NBACard(
            case_id=ctx.case_id,
            golden_customer_id=ctx.golden_customer_id,
            model_version=self._scorer.model_version,
            features_as_of=ctx.features_as_of,
            headline=_headline(best.action, slot, ctx),
            proposal=proposal,
            probabilities=probs,
            reasons=tuple(reasons),
            sizing_text=proposal.sizing.rationale if proposal.sizing else None,
            checks=checks.get(best.action, ()),
            hardship_banner=_banner(ctx),
        )

    def _legacy(
        self,
        ctx: CaseContext,
        allowed: list[Action],
        checks: Mapping[Action, tuple[CheckResult, ...]],
        slot: tuple[datetime, datetime] | None,
    ) -> NBACard:
        why = "kill switch on" if self._kill_switch else "hold-out case"
        a = ctx.legacy_action
        if a is None or a is Action.WAIT or a not in allowed:
            return self._no_action(
                ctx, f"No action: old strategy ({why}) has no allowed action for this case."
            )
        sizing = _sizing(ctx) if a in _SIZED else None
        if a in _SIZED and sizing is None:
            return self._no_action(
                ctx, f"No action: old strategy ({why}) asks for a promise that can't be kept."
            )
        tier = assign_tier(action=a, hard_stopped=False, hardship_status=_protective_status(ctx))
        proposal = self._proposal(ctx, a, tier, slot, sizing, legacy=True)
        return NBACard(
            case_id=ctx.case_id,
            golden_customer_id=ctx.golden_customer_id,
            model_version="legacy",
            features_as_of=ctx.features_as_of,
            headline=f"{_LABEL[a]} (old strategy: {why})",
            proposal=proposal,
            probabilities=(),
            sizing_text=sizing.rationale if sizing else None,
            checks=checks.get(a, ()),
            hardship_banner=_banner(ctx),
        )

    def _proposal(
        self,
        ctx: CaseContext,
        action: Action,
        tier: object,
        slot: tuple[datetime, datetime] | None,
        sizing: PromiseSizing | None,
        *,
        legacy: bool = False,
    ) -> Proposal:
        return Proposal.model_validate(
            {
                "proposal_id": f"P-{new_event_id()}",
                "case_id": ctx.case_id,
                "golden_customer_id": ctx.golden_customer_id,
                "action": action,
                "channel": ACTION_CHANNEL[action],
                "window_start": slot[0] if slot else None,
                "window_end": slot[1] if slot else None,
                "sizing": sizing,
                "tier": tier,
                "model_version": "legacy" if legacy else self._scorer.model_version,
                "features_as_of": ctx.features_as_of,
                "created_at": ctx.now,
                "expires_at": ctx.now + PROPOSAL_TTL,
                "is_legacy_strategy": legacy,
            }
        )

    def _no_action(
        self,
        ctx: CaseContext,
        reason: str,
        *,
        hard_stop: object = None,
        probabilities: tuple[Alternative, ...] = (),
    ) -> NBACard:
        return NBACard.model_validate(
            {
                "case_id": ctx.case_id,
                "golden_customer_id": ctx.golden_customer_id,
                "model_version": self._scorer.model_version,
                "features_as_of": ctx.features_as_of,
                "headline": "No action today",
                "proposal": None,
                "probabilities": probabilities,
                "hardship_banner": _banner(ctx),
                "hard_stop": hard_stop,
                "no_action_reason": reason,
            }
        )


# ------------------------------------------------------------------ helpers
def _model_frame(fv: FeatureVector) -> pd.DataFrame:
    row = fv.model_dump()
    return pd.DataFrame([{n: row.get(n) for n in model_inputs()}])


def _sizing(ctx: CaseContext) -> PromiseSizing | None:
    today = ctx.now.astimezone(ZoneInfo(ctx.time_zone)).date() if ctx.time_zone else ctx.now.date()
    return size_promise(
        balance_due=ctx.balance_at_risk,
        spare_cash_monthly=ctx.estimated_monthly_spare_cash,
        expected_payday=ctx.expected_next_payroll_date,
        payroll_frequency=ctx.payroll_frequency,
        today=today,
    )


def _protective_status(ctx: CaseContext) -> HardshipStatus:
    if ctx.hardship_status is HardshipStatus.NONE and ctx.vulnerable:
        return HardshipStatus.POSSIBLE  # vulnerability is released like hardship: Red tier
    return ctx.hardship_status


def _alternatives(best: Action, ranked: list[ActionScore]) -> tuple[Alternative, ...]:
    rest = sorted((s for s in ranked if s.action is not best), key=lambda s: -s.p_paid_14d)
    top = next(s for s in ranked if s.action is best)
    return tuple(Alternative(action=s.action, p_paid_14d=s.p_paid_14d) for s in (top, *rest))


def _banner(ctx: CaseContext) -> str | None:
    if ctx.hardship_status is HardshipStatus.CONFIRMED:
        return "Confirmed hardship: only protective actions; a hardship specialist releases them."
    if ctx.hardship_status is HardshipStatus.POSSIBLE:
        return "Possible hardship: only protective actions; a hardship specialist reviews first."
    if ctx.vulnerable:
        return "Vulnerable customer: only protective actions; a hardship specialist reviews first."
    return None


def _headline(action: Action, slot: tuple[datetime, datetime] | None, ctx: CaseContext) -> str:
    if slot is None or ACTION_CHANNEL[action] is None:
        return _LABEL[action]
    tz = ZoneInfo(ctx.time_zone)
    s, e = slot[0].astimezone(tz), slot[1].astimezone(tz)
    return f"{_LABEL[action]}, {s:%a %H:%M}-{e:%H:%M} customer time"
