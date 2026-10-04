"""Decisioning contracts (Layer 4 -> app/UI, and the release gate)."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from kept.config import CALLING_HOURS_END, CALLING_HOURS_START, CONTACT_CAP_7D, TOP_REASONS
from kept.contracts.enums import (
    Action,
    Channel,
    HardshipStatus,
    HardStop,
    PayrollFrequency,
    ReleaseTier,
    ReviewDecision,
    Role,
)
from kept.contracts.identity import ContactPermissions

Probability = Annotated[float, Field(ge=0.0, le=1.0)]
Money = Annotated[Decimal, Field(ge=0, decimal_places=2)]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _require_aware(v: datetime | None) -> datetime | None:
    if v is not None and v.tzinfo is None:
        raise ValueError("datetimes must be timezone-aware")
    return v


class CaseContext(_Frozen):
    """Everything the rule stages need about one case, read fresh from C360 + features."""

    case_id: str
    golden_customer_id: str
    assigned_agent_id: str | None
    now: datetime
    time_zone: str  # IANA; calling hours are customer-local
    hard_stop_flags: frozenset[HardStop] = frozenset()
    contact_permissions: ContactPermissions
    permitted_call_start_local: time = CALLING_HOURS_START  # per customer, from CRM
    permitted_call_end_local: time = CALLING_HOURS_END
    sunday_contact_permitted: bool = False
    do_not_contact: bool
    contacts_last_7d: int = Field(ge=0)
    contact_cap_7d: int = Field(default=CONTACT_CAP_7D, ge=0)  # collections_cases.contact_cap_7d
    hardship_status: HardshipStatus
    vulnerable: bool = False  # vulnerability signal: same protection as hardship
    balance_at_risk: Money
    expected_next_payroll_date: date | None = None
    payroll_frequency: PayrollFrequency = PayrollFrequency.UNKNOWN
    estimated_monthly_spare_cash: Decimal | None = None
    in_holdout: bool = False
    legacy_action: Action | None = None  # nba_recommendation_last
    features_as_of: datetime

    _v_now = field_validator("now", "features_as_of")(_require_aware)

    @model_validator(mode="after")
    def _window(self) -> CaseContext:
        if self.permitted_call_end_local <= self.permitted_call_start_local:
            raise ValueError("permitted_call_end_local must be after permitted_call_start_local")
        return self


class HardStopResult(_Frozen):
    blocked: bool
    fired: tuple[HardStop, ...] = ()
    rule_card: str | None = None  # what the agent sees: which rule fired and why

    @model_validator(mode="after")
    def _consistent(self) -> HardStopResult:
        if self.blocked != bool(self.fired):
            raise ValueError("blocked must be True exactly when at least one rule fired")
        return self


class CheckName(StrEnum):
    CONSENT = "consent"
    CALLING_HOURS = "calling_hours"
    CONTACT_CAP = "contact_cap"
    DO_NOT_CONTACT = "do_not_contact"


class CheckResult(_Frozen):
    check: CheckName
    passed: bool
    detail: str  # e.g. "2 of 3 contacts this week"


class PermissionResult(_Frozen):
    action: Action
    allowed: bool
    checks: tuple[CheckResult, ...]

    @model_validator(mode="after")
    def _consistent(self) -> PermissionResult:
        if self.allowed != all(c.passed for c in self.checks):
            raise ValueError("allowed must equal all(check.passed)")
        return self


class ActionScore(_Frozen):
    action: Action
    p_paid_14d: Probability  # P(paid within 14 days | action)
    uplift: float = Field(ge=-1.0, le=1.0)  # vs WAIT
    expected_value: Decimal  # uplift x balance at risk
    contact_cost: Decimal = Field(ge=0)
    burden: Decimal = Field(ge=0)
    score: Decimal  # expected_value - contact_cost - burden


class PromiseSizing(_Frozen):
    """Kept sizing: plain arithmetic, no model."""

    amount: Money = Field(gt=0)
    due_date: date
    installments: int = Field(ge=1)  # 1 = single promise; 3 = "3-month plan"
    spare_cash_estimate: Money  # spare cash per pay period (monthly for monthly pay)
    payday: date
    rationale: str  # "$140 fits inside estimated spare cash of ~$160 ..."

    @model_validator(mode="after")
    def _within_spare_cash(self) -> PromiseSizing:
        if self.amount > self.spare_cash_estimate:
            raise ValueError("promise amount must stay within estimated spare cash")
        return self


class Reason(_Frozen):
    feature: str
    sentence: str  # fixed template sentence, never LLM text
    contribution_pts: float  # percentage points toward the recommended action


class ProposalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    RELEASED = "released"
    EXPIRED = "expired"
    CANCELLED = "cancelled"  # payment or cease landed
    REJECTED = "rejected"


class Proposal(_Frozen):
    """A record that a person approves. The model never sends anything itself."""

    proposal_id: str
    case_id: str
    golden_customer_id: str
    action: Action
    channel: Channel | None
    window_start: datetime | None = None
    window_end: datetime | None = None
    sizing: PromiseSizing | None = None
    tier: ReleaseTier
    model_version: str
    features_as_of: datetime
    created_at: datetime
    expires_at: datetime
    status: ProposalStatus = ProposalStatus.PENDING
    is_legacy_strategy: bool = False  # hold-out or kill switch

    _v_dt = field_validator("window_start", "window_end", "features_as_of", "created_at", "expires_at")(
        _require_aware
    )

    @model_validator(mode="after")
    def _ordering(self) -> Proposal:
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be after created_at")
        if (self.window_start is None) != (self.window_end is None):
            raise ValueError("window_start and window_end go together")
        if self.window_start and self.window_end and self.window_end <= self.window_start:
            raise ValueError("window_end must be after window_start")
        return self


class Alternative(_Frozen):
    action: Action
    p_paid_14d: Probability


class NBACard(_Frozen):
    """What the agent sees (architecture page, bottom panel)."""

    case_id: str
    golden_customer_id: str
    model_version: str
    features_as_of: datetime
    headline: str
    proposal: Proposal | None  # None means "no action"
    probabilities: tuple[Alternative, ...]  # recommended first, includes WAIT
    reasons: tuple[Reason, ...] = Field(default=(), max_length=TOP_REASONS)
    sizing_text: str | None = None
    similar_cases_text: str | None = None  # "(descriptive, not causal)"
    legacy_text: str | None = None  # the bank's current strategy for this case, next to ours
    checks: tuple[CheckResult, ...] = ()
    hardship_banner: str | None = None
    hard_stop: HardStopResult | None = None
    no_action_reason: str | None = None  # stale data, error, hard stop


class ReleaseDecision(_Frozen):
    proposal_id: str
    reviewer_id: str
    reviewer_role: Role
    decision: ReviewDecision
    decided_at: datetime
    edited_amount: Money | None = None
    edited_due_date: date | None = None
    alternative_action: Action | None = None
    override_reason: str | None = None
    second_reviewer_id: str | None = None  # Red tier needs a second person
    second_reviewer_role: Role | None = None

    _v_dt = field_validator("decided_at")(_require_aware)

    @model_validator(mode="after")
    def _shape(self) -> ReleaseDecision:
        if self.decision is ReviewDecision.OVERRIDE and not (self.override_reason or "").strip():
            raise ValueError("override needs a reason")
        if self.decision is ReviewDecision.ALTERNATIVE and self.alternative_action is None:
            raise ValueError("alternative needs alternative_action")
        if (
            self.decision is ReviewDecision.EDIT
            and self.edited_amount is None
            and self.edited_due_date is None
        ):
            raise ValueError("edit needs an edited amount or date")
        if self.second_reviewer_id is not None and self.second_reviewer_id == self.reviewer_id:
            raise ValueError("second reviewer must be a different person")
        return self


class ReleaseResult(_Frozen):
    proposal_id: str
    released: bool
    reason: str  # why released, or why not (consent changed, expired, wrong role ...)
    audit_event_id: str
    executed_at: datetime | None = None
