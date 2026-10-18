# ruff: noqa: E501  (docstrings)
"""Runs stages 1-7 and builds the NBA card. Implements NBAEngine."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd

from kept.common.audit import new_event_id
from kept.config import CLOSE_CALL_MARGIN, PROPOSAL_TTL
from kept.contracts.audit import AuditEvent, AuditKind
from kept.contracts.enums import ACTION_CHANNEL, Action, Channel, HardshipStatus
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
    StatedPay,
)
from kept.nba.explain import drivers, top_reasons
from kept.nba.promise_model import PromiseModel, serving_row
from kept.nba.ranking import CallCapacity, is_close_call, score_actions
from kept.nba.release import cancel_pending, is_stale
from kept.nba.rules import allowed_actions, hard_stops, hardship_override, permission_gate
from kept.nba.sizing import promise_options, size_promise
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
        if s > start:  # agents book round slots: start on the next half hour
            up = s.replace(minute=0, second=0, microsecond=0)
            while up < s:
                up += timedelta(minutes=30)
            s = up
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
        programs: Callable[[CaseContext], Sequence[str]] | None = None,
        drift_alarm: Sequence[str] = (),
        promise_model: PromiseModel | None = None,
        call_capacity: CallCapacity | None = None,
        rank_promises: bool = False,
    ) -> None:
        """proposals: where new proposals are stored for the release gate (Releaser reads it).
        programs: hardship programmes the case is eligible for, named for the banner
        (C's hardship.programs.eligible_programs at G3; the demo reads hardship_programs)."""
        self._context = context
        self._features = features
        self._scorer = scorer
        self._log = audit_log
        self._kill_switch = kill_switch
        self._proposals = proposals if proposals is not None else {}
        self._cost = contact_cost
        self._burden = burden
        self._programs = programs
        self._drift = tuple(drift_alarm)  # model inputs that shifted overnight (#86): Green goes to a person
        self._promise = promise_model  # explains a sized promise on the card, never ranks it (#79)
        self._calls = call_capacity  # the nightly batch books calls into hours with capacity
        self._rank_promises = rank_promises  # value promise asks by reach x agree x keep (`_ask_chain`); off by default

    def payment_options(
        self, case_id: str, now: datetime, stated: StatedPay | None = None
    ) -> list[PromiseSizing]:
        """Every payday-dated plan within spare cash (#89, the customer page). With `stated`, the
        customer's own next payday, pay frequency and amount per payday replace the bank's.
        KeyError if unknown."""
        ctx = self._context.build(case_id, now)
        today = ctx.now.astimezone(ZoneInfo(ctx.time_zone)).date() if ctx.time_zone else ctx.now.date()
        return promise_options(
            balance_due=ctx.balance_at_risk,
            spare_cash_monthly=ctx.estimated_monthly_spare_cash,
            expected_payday=stated.next_payday if stated else ctx.expected_next_payroll_date,
            payroll_frequency=stated.frequency if stated else ctx.payroll_frequency,
            today=today,
            stated_per_payday=stated.per_payday if stated else None,
        )

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
        # one live proposal per case: a fresh recommendation retires the older pending one, and so does a
        # "no action" card (a cease or hold that just landed), so it leaves the approvals inbox too
        cancel_pending(
            case_id,
            reason="superseded by a newer recommendation"
            if card.proposal is not None
            else (card.no_action_reason or "no action now"),
            proposals=self._proposals,
            audit_log=self._log,
            now=now,
        )
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
        if ctx.hardship_plan_until:  # #93: a running plan is already the hardship review's outcome
            allowed = [a for a in allowed if a is not Action.HARDSHIP_REVIEW]
        checks = {r.action: r.checks for r in results}

        if self._kill_switch or ctx.in_holdout:
            return self._legacy(ctx, allowed, checks, slot)

        fv = self._features.get_online(ctx.case_id)
        X = _model_frame(fv)
        proba = self._scorer.predict_proba(X).iloc[0]  # stage 4
        model_of = _scored_as(proba.index, protective=_protective_status(ctx) is not HardshipStatus.NONE)
        p_paid = {a: float(proba[model_of[a].value]) for a in allowed if a in model_of}

        sizing = _sizing(ctx)  # stage 5
        if sizing is None:
            p_paid = {a: p for a, p in p_paid.items() if a not in _SIZED}

        chain = self._ask_chain(ctx, fv, X, sizing, slot, set(p_paid)) if self._rank_promises else None
        ranked = score_actions(  # stage 6
            p_paid=p_paid,
            balance_at_risk=ctx.balance_at_risk,
            contact_cost=self._cost,
            burden=self._burden,
            p_kept_given_promise=chain,
        )
        best = ranked[0]
        if best.action is Action.WAIT and _protective_status(ctx) is not HardshipStatus.NONE:
            # the hardship override sits outside the model (design §6.3): when the customer is
            # protected and a hardship review is allowed, offer it rather than "no action", even
            # if no contact pays more in 14 days. Red tier: a specialist still decides.
            best = next((s for s in ranked if s.action is Action.HARDSHIP_REVIEW), best)
        if best.action is Action.CALL and sizing is not None:
            # a call that can carry a payday-dated promise asks for one: same contact and cost, a sized
            # ask (#79). Promise and plan score like the call (they borrow its model), so only a tie or
            # better switches; a plan when the amount needs instalments; never a non-call action.
            asks = (Action.PAYMENT_PLAN, Action.PROMISE_REQUEST)
            asks = asks if sizing.installments > 1 else asks[::-1]
            best = next((s for a in asks for s in ranked if s.action is a and s.score >= best.score), best)
        probs = _alternatives(best.action, ranked)
        legacy = _legacy_text(ctx.legacy_action, best.action, proba, model_of, allowed)
        if best.action is Action.WAIT:
            plan = ctx.hardship_plan_until
            return self._no_action(
                ctx,
                f"Monitoring the hardship plan: it runs until {plan:%b %-d, %Y}, so no new review is needed. "
                "Every protection still applies."
                if plan
                else "Best action is to wait: no contact beats waiting today.",
                probabilities=probs,
                legacy_text=legacy,
            )

        reasons, why = [], []  # stage 7
        explain = getattr(self._scorer, "contributions", None)
        if explain is not None:
            values = fv.model_dump()
            contrib = explain(X, model_of[best.action])
            reasons, why = top_reasons(contrib, values), drivers(contrib, values)
        tier = assign_tier(
            action=best.action,
            hard_stopped=False,
            hardship_status=_protective_status(ctx),
            close_call=is_close_call(ranked, margin=CLOSE_CALL_MARGIN) or bool(self._drift),
        )
        slot, checks, booked_note = self._book(ctx, best.action, slot, checks, X)
        proposal = self._proposal(ctx, best.action, tier, slot, sizing if best.action in _SIZED else None)
        why_not_line = why_not(best, ranked)
        return NBACard(
            case_id=ctx.case_id,
            golden_customer_id=ctx.golden_customer_id,
            model_version=self._scorer.model_version,
            features_as_of=ctx.features_as_of,
            headline=_headline(best.action, slot, ctx),
            proposal=proposal,
            probabilities=probs,
            reasons=tuple(reasons),
            drivers=tuple(why),
            sizing_text=self._sizing_text(ctx, fv, proposal.sizing) if proposal.sizing else None,
            similar_cases_text=similar_cases(fv, best.action),
            legacy_text=legacy,
            why_not_text=why_not_line,
            booking_text=booked_note,  # best-hour booking moved the call: say so, with the model's numbers
            checks=checks.get(best.action, ()),
            hardship_banner=self._banner(ctx),
        )

    def _ask_chain(
        self,
        ctx: CaseContext,
        fv: FeatureVector,
        X: pd.DataFrame,
        sizing: PromiseSizing | None,
        slot: tuple[datetime, datetime] | None,
        allowed: set[Action],
    ) -> dict[Action, float] | None:
        """What a promise ask is worth as a probability, for `score_actions`' p_kept_given_promise: P(the call reaches the
        right party at its slot) x P(a promise is made | reached) x P(kept | promise). P(reached) comes from the best-hour
        model at the slot's local hour when the capacity book has one, else the promise model's overall rate; the other two
        from the promise model (observed rate of promises made on reached calls, and its kept chance for this sizing).
        None (the asks keep scoring like the call) when a piece is missing. ponytail: one P(promise | reached) for everyone,
        and the plan reuses the promise's kept chance; segment it if the check below ever supports turning this on."""
        pm_ = self._promise
        agree = getattr(pm_, "p_promise_given_rpc", None)
        if pm_ is None or sizing is None or agree is None or not (set(_SIZED) & allowed):
            return None
        try:
            p_kept = self._p_kept(ctx, fv, sizing)[0]
            reach = getattr(pm_, "p_rpc", None)
            hour_model = self._calls.best_hour if self._calls is not None else None
            if hour_model is not None and slot is not None:
                local = slot[0].astimezone(ZoneInfo(ctx.time_zone))
                reach = float(hour_model.p_rpc(X, [(local.hour, local.weekday())])[0])
            if reach is None:
                return None
        except Exception:
            return None
        return {a: reach * agree * p_kept for a in _SIZED}

    def _p_kept(self, ctx: CaseContext, fv: FeatureVector, sizing: PromiseSizing) -> tuple[float, float]:
        """The promise model's chance this promise is kept, and if it fell due the day before payday."""
        assert self._promise is not None
        today = ctx.now.astimezone(ZoneInfo(ctx.time_zone)).date() if ctx.time_zone else ctx.now.date()
        freq = ctx.payroll_frequency.value if ctx.payroll_frequency else None
        common = {
            "today": today,
            "payday": sizing.payday,
            "frequency": freq,
            "dpd": fv.max_dpd,
            "prior_broken_90d": fv.broken_promises_90d,
            "prior_kept_ratio": fv.kept_promise_ratio,
        }
        ours = serving_row(due=sizing.due_date, **common)  # type: ignore[arg-type]
        before = serving_row(due=sizing.payday - timedelta(days=1), **common)  # type: ignore[arg-type]
        p_ours, p_before = self._promise.p_kept([ours, before])
        return float(p_ours), float(p_before)

    def _sizing_text(self, ctx: CaseContext, fv: FeatureVector, sizing: PromiseSizing) -> str:
        """The sizing rationale, plus the promise model's chance it's kept on this date and on a date
        just before payday (#79). A model failure never costs the card: the rationale stays."""
        if self._promise is None:
            return sizing.rationale
        try:
            p_ours, p_before = self._p_kept(ctx, fv, sizing)
        except Exception:
            return sizing.rationale
        chance = f"If they agree, the model gives this promise a {p_ours:.0%} chance of being kept"
        if round(p_ours * 100) == round(p_before * 100):  # the date makes no visible difference here
            return f"{sizing.rationale} {chance}."
        return f"{sizing.rationale} {chance} ({p_before:.0%} if it fell due the day before payday)."

    def _book(
        self,
        ctx: CaseContext,
        action: Action,
        slot: tuple[datetime, datetime] | None,
        checks: Mapping[Action, tuple[CheckResult, ...]],
        features: pd.DataFrame | None = None,
    ) -> tuple[tuple[datetime, datetime] | None, Mapping[Action, tuple[CheckResult, ...]], str | None]:
        """A call goes into the earliest hour with call capacity (nightly batch only); its checks are
        rerun at the booked time. With the best-hour model on the capacity book and the case's `features`, it
        goes into the likeliest-to-answer hour of that same day; the third value says so when it moved it."""
        if self._calls is None or slot is None or ACTION_CHANNEL[action] is not Channel.CALL:
            return slot, checks, None
        if self._calls.best_hour is not None and features is not None:
            booked, moved = self._calls.book_best(ctx, slot, features)
        else:
            booked, moved = self._calls.book(ctx, slot), None
        if booked == slot:
            return slot, checks, None
        rerun = permission_gate(ctx.model_copy(update={"now": booked[0]}), action).checks
        return booked, {**checks, action: rerun}, moved.text() if moved else None

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
        slot, checks, _ = self._book(ctx, a, slot, checks)
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
            hardship_banner=self._banner(ctx),
        )

    def _banner(self, ctx: CaseContext) -> str | None:
        """The hardship banner, naming eligible programmes when there are any. A failing
        programmes lookup never costs the card: the banner just goes without them."""
        text = _banner(ctx)
        if text is None or self._programs is None:
            return text
        try:
            names = list(self._programs(ctx))
        except Exception:
            names = []
        return f"{text} Eligible programmes: {'; '.join(names)}." if names else text

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
        legacy_text: str | None = None,
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
                "hardship_banner": self._banner(ctx),
                "hard_stop": hard_stop,
                "no_action_reason": reason,
                "legacy_text": legacy_text,
            }
        )


# ------------------------------------------------------------------ helpers
_CALLS = (Action.CALL, Action.PROMISE_REQUEST, Action.PAYMENT_PLAN, Action.HARDSHIP_REVIEW)  # one call model


def why_not(best: ActionScore, ranked: Sequence[ActionScore]) -> str | None:
    """ "Why this, not that": the chosen action against the best-scoring other kind of action, in points
    of payment chance over waiting and in value after contact cost and customer burden. Template only."""
    family = _CALLS if best.action in _CALLS else (best.action,)
    runner = next((s for s in ranked if s.action not in family), None)
    if runner is None or best.action is Action.WAIT:
        return None
    if best.score < runner.score:  # a protection chose it (the hardship override), not value
        other = "Waiting" if runner.action is Action.WAIT else f"To {_LABEL[runner.action].lower()}"
        return (
            f"{other} would be worth ${runner.score - best.score:,.2f} more on value alone; this action is "
            "chosen because the case's protections come first."
        )
    gain = f"{_LABEL[best.action]} adds {100 * best.uplift:.1f} points to the chance of payment over waiting"
    if runner.action is Action.WAIT:
        return (
            f"{gain}; after contact cost and the burden on the customer it is worth "
            f"${best.score:,.2f} more than waiting."
        )
    return (
        f"{gain}; to {_LABEL[runner.action].lower()} adds {100 * runner.uplift:.1f}. After contact cost "
        f"and the burden on the customer, it is worth ${best.score - runner.score:,.2f} more."
    )


def _legacy_text(
    legacy: Action | None,
    ours: Action,
    proba: pd.Series,
    model_of: Mapping[Action, Action],
    allowed: Sequence[Action],
) -> str:
    """One line comparing the bank's current strategy (nba_recommendation_last) with our choice,
    in the same model's chance of payment within 14 days."""

    def chance(a: Action) -> str | None:
        return f"{proba[model_of[a].value]:.0%}" if a in model_of else None

    if legacy is None:
        return "The bank's current strategy has no action for this case."
    if legacy is ours:
        return "Same as the bank's current strategy."
    p_old, p_ours = chance(legacy), chance(ours)
    notes = [
        f"{p_old} chance of payment in 14 days" if p_old else "our model doesn't score it for this customer"
    ]
    if legacy not in allowed:
        notes.append("and it isn't allowed for this customer today")
    ours_text = _LABEL[ours].lower() + (f" ({p_ours})" if p_ours else "")
    old = f"The bank's current strategy would: {_LABEL[legacy].lower()} ({', '.join(notes)})"
    return f"{old}. Ours: {ours_text}."


_CALL_CONVERSATIONS = (Action.PROMISE_REQUEST, Action.PAYMENT_PLAN, Action.HARDSHIP_REVIEW)


def _scored_as(fitted: Iterable[str], *, protective: bool) -> dict[Action, Action]:
    """Which model scores each action. The random test cells never assigned promise, plan or
    hardship-review conversations, so the trained model has no arm for them; they are calls,
    so they take the call model's P(paid). Hardship review only when hardship or vulnerability
    protects the case: with the call's P(paid) and a lower burden it would otherwise beat every call.
    Actions with no model drop out of the ranking.
    ponytail: borrowed call probability: promise and plan tie with the call, so a call that can carry a sized ask
    asks. `KeptEngine(rank_promises=True)` values them instead by reach x agree x keep (`_ask_chain`, ranking's
    p_kept_given_promise): off by default, because nothing offline can test it (see docs/reports/promise_ranking.md)."""
    names = set(fitted)
    out = {a: a for a in Action if a.value in names}
    if Action.EMAIL in out:  # a pooled "digital nudge" model (kept train --pool-nudges) scores all three
        for a in (Action.PUSH, Action.SMS_PAYMENT_LINK):
            out.setdefault(a, Action.EMAIL)
    if Action.CALL in out:
        for a in _CALL_CONVERSATIONS:
            if a not in out and (protective or a is not Action.HARDSHIP_REVIEW):
                out[a] = Action.CALL
    return out


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


# Resolved promises by days since the customer's last salary credit (scripts/business_case.py, release data):
# due 0-2 days after payday 54.3% kept (8,359), 8+ days after 46.3% (16,045). Descriptive, not causal.
PAYDAY_KEPT_PCT, LATE_KEPT_PCT = 54, 46


def similar_cases(fv: FeatureVector, action: Action) -> str | None:
    """The card's "similar cases" line (design §6.7): what happened to past cases of the same product and
    delinquency stage, plus the payday finding for a promise or plan. Descriptive, never causal."""
    parts = []
    if fv.cohort_kept_rate is not None:
        parts.append(f"{fv.cohort_kept_rate:.0%} of their promises were kept")
    if fv.cohort_recovery_rate is not None:
        parts.append(f"{fv.cohort_recovery_rate:.0%} recovered")
    line = f"Similar past cases (same product and stage): {' and '.join(parts)}." if parts else ""
    if action in _SIZED:
        line += (
            f" Past promises due 0-2 days after payday were kept {PAYDAY_KEPT_PCT}% of the time, against"
            f" {LATE_KEPT_PCT}% when due 8+ days after."
        )
    return f"{line.strip()} (Descriptive, not causal.)" if line else None


def _headline(action: Action, slot: tuple[datetime, datetime] | None, ctx: CaseContext) -> str:
    if slot is None or ACTION_CHANNEL[action] is None:
        return _LABEL[action]
    tz = ZoneInfo(ctx.time_zone)
    s, e = slot[0].astimezone(tz), slot[1].astimezone(tz)
    return f"{_LABEL[action]}, {s:%a %H:%M}-{e:%H:%M} customer time"
