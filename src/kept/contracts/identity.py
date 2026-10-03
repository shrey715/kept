"""Identity resolution and the golden customer record (Layer 1 -> everyone).

GoldenCustomer mirrors gold.c360_customer in contracts/c360_customer.odcs.yaml
column for column. tests/contracts/test_contract_consistency.py enforces that.
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from kept.config import GOLDEN_ID_PATTERN
from kept.contracts.enums import (
    DpdBucket,
    HardshipSource,
    HardshipStatus,
    MatchReviewStatus,
    MatchRoute,
    PayrollFrequency,
    SourceSystem,
)

GoldenId = Annotated[str, Field(pattern=GOLDEN_ID_PATTERN)]
E164 = Annotated[str, Field(pattern=r"^\+[1-9]\d{6,14}$")]
Score = Annotated[float, Field(ge=0.0, le=1.0)]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SourceKey(_Frozen):
    """One customer key in one product system."""

    system: SourceSystem
    key: Annotated[str, Field(min_length=1)]


class ContactPermissions(_Frozen):
    """Consent per channel. Unknown consent is False (most restrictive)."""

    call: bool = False
    sms: bool = False
    email: bool = False
    push: bool = False


class GoldenCustomer(_Frozen):
    """One row of gold.c360_customer, one per golden_customer_id."""

    golden_customer_id: GoldenId
    source_keys: tuple[SourceKey, ...] = Field(min_length=1)
    match_confidence_min: Score | None = None  # weakest link in the cluster
    match_review_status: MatchReviewStatus

    # Direct PII (masked for agents in the UI; never sent to an LLM unredacted)
    display_name: str | None = None
    primary_phone_e164: E164 | None = None
    email: str | None = None

    # Quasi-identifiers (routing only; never model features)
    province_code: Annotated[str, Field(pattern=r"^[A-Z]{2}$")] | None = None
    time_zone: str | None = None  # IANA, e.g. America/Toronto
    preferred_language: str | None = None

    # Delinquency across current account snapshots
    total_overdue: Decimal = Field(ge=0)
    max_dpd: int = Field(ge=0)
    current_bucket: DpdBucket

    open_case_id: str | None = None
    assigned_agent_id: str | None = None

    contact_permissions: ContactPermissions
    permitted_call_start_local: time | None = None  # customers.permitted_call_start_local
    permitted_call_end_local: time | None = None  # customers.permitted_call_end_local
    sunday_contact_permitted: bool = False
    do_not_contact: bool  # any source do-not-call or cease (never national_dncl_flag)
    collections_hold: bool  # any insolvency, bankruptcy or deceased flag

    hardship_status: HardshipStatus
    hardship_source: HardshipSource | None = None
    vulnerability_flag: bool = False  # customers.vulnerability_flag; protects like hardship

    expected_next_payroll_date: date | None = None
    payroll_frequency_detected: PayrollFrequency = PayrollFrequency.UNKNOWN

    # Lineage
    as_of_date: date
    refreshed_at: datetime
    display_name_source: str | None = None
    primary_phone_e164_source: str | None = None
    email_source: str | None = None
    province_code_source: str | None = None
    time_zone_source: str | None = None
    preferred_language_source: str | None = None
    total_overdue_source: str | None = None
    contact_permissions_source: str | None = None
    do_not_contact_source: str | None = None
    collections_hold_source: str | None = None
    expected_next_payroll_date_source: str | None = None

    @field_validator("refreshed_at")
    @classmethod
    def _aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("refreshed_at must be timezone-aware")
        return v


class CrosswalkEntry(_Frozen):
    """One row of gold.identity_crosswalk: a source key and the golden ID it maps to."""

    golden_customer_id: GoldenId
    source_key: SourceKey
    match_score: Score | None = None  # None for exact links
    match_rule: str  # e.g. "exact:national_id_hash", "splink"
    match_review_status: MatchReviewStatus
    linked_at: datetime
    valid_to: datetime | None = None  # set when a split or merge retires this link


class CandidatePair(_Frozen):
    left: SourceKey
    right: SourceKey
    score: Score
    rule: str  # "exact:<key>" or "splink"


class MatchDecision(_Frozen):
    pair: CandidatePair
    route: MatchRoute
    reasons: tuple[str, ...] = ()


class ClusterEvent(_Frozen):
    """Merge/split log entry. Every link can be undone by replaying the inverse."""

    event_id: str
    kind: Annotated[str, Field(pattern=r"^(merge|split|undo)$")]
    golden_ids_before: tuple[GoldenId, ...]
    golden_ids_after: tuple[GoldenId, ...]
    source_keys: tuple[SourceKey, ...]
    actor_id: str
    reason: str
    at: datetime
    undoes_event_id: str | None = None
