"""Feature store and text-extraction contracts (Layer 3 -> Layer 4).

FeatureVector field names must equal kept.contracts.feature_registry.FEATURES.
Every value is Optional: missing stays missing (never fill with 0 here).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from kept.contracts.enums import HardshipSignal, PayrollFrequency

T = TypeVar("T")


class RedactedText(BaseModel):
    """Text that has been through Presidio. The only text type the LLM gateway accepts.

    Construct it only in kept.text.redact. Holding a RedactedText is the claim
    "personal details have been stripped"; the type is how we enforce
    "PII redaction before any LLM" (design §9).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    entity_types_removed: tuple[str, ...] = ()
    redactor_version: str


class Evidence(BaseModel):
    """The quote that supports an extracted value. Must be a substring of the redacted input."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    quote: Annotated[str, Field(min_length=1)]
    source_id: str  # note_id or call_id
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)


class ExtractedValue(BaseModel, Generic[T]):
    model_config = ConfigDict(frozen=True, extra="forbid")

    value: T
    evidence: Evidence | None = None  # None only when value is the "nothing found" value
    confidence: float = Field(ge=0.0, le=1.0)


class StatedReason(StrEnum):
    """Why the customer says they can't pay. Triggers hardship handling only; never a feature."""

    NONE = "none"
    JOB_LOSS = "job_loss"
    REDUCED_INCOME = "reduced_income"
    MEDICAL = "medical"
    BEREAVEMENT = "bereavement"
    OTHER = "other"


class TextExtraction(BaseModel):
    """What the LLM (or SetFit backfill) returns for one note or call transcript."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str
    case_id: str
    hardship_signal: ExtractedValue[HardshipSignal]
    stated_reason: ExtractedValue[StatedReason]  # routes to hardship handling, never the model
    promise_intent: ExtractedValue[bool]
    promised_date: ExtractedValue[date | None]
    promised_amount: ExtractedValue[Decimal | None]
    dispute: ExtractedValue[bool]
    cease_request: ExtractedValue[bool]  # feeds the hard stops
    third_party_present: ExtractedValue[bool]  # feeds the hard stops
    extractor: Annotated[str, Field(pattern=r"^(llm|setfit):")]  # e.g. "llm:prompt-v3"
    extracted_at: datetime
    confirmed_by_agent_id: str | None = None  # agent confirms or edits at wrap-up


class FeatureVector(BaseModel):
    """Feature values for one case as of one decision time (point in time)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    golden_customer_id: str
    as_of: datetime
    feature_set_version: str

    # Delinquency (C360 accounts, collections cases)
    max_dpd: int | None = None
    times_30plus_dpd_12m: int | None = None
    days_in_bucket: int | None = None
    balance_at_risk: Decimal | None = None

    # Promises to pay
    broken_promises_90d: int | None = None
    kept_promise_ratio: float | None = None

    # Deposits / payroll
    days_to_next_payroll: int | None = None
    pay_frequency: PayrollFrequency | None = None
    payroll_delay_days: int | None = None
    pay_change_vs_3m_avg: float | None = None
    estimated_monthly_spare_cash: Decimal | None = None

    # Deposit and card history
    cash_flow_trend: float | None = None
    card_utilisation_trend: float | None = None

    # Contact history
    answer_rate: float | None = None
    answer_rate_after_18h: float | None = None
    payment_link_usage: float | None = None
    contacts_last_7d: int | None = None

    # Cohort stats (groups of 50+, else None)
    cohort_recovery_rate: float | None = None
    cohort_kept_rate: float | None = None

    # Text (LLM on notes and calls)
    hardship_signal: HardshipSignal | None = None
    promise_intent: bool | None = None
    promised_date: date | None = None
    promised_amount: Decimal | None = None
    dispute_flag: bool | None = None
    cease_request_flag: bool | None = None
    third_party_present_flag: bool | None = None

    @field_validator("as_of")
    @classmethod
    def _aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        return v

    @classmethod
    def feature_names(cls) -> tuple[str, ...]:
        meta = {"case_id", "golden_customer_id", "as_of", "feature_set_version"}
        return tuple(n for n in cls.model_fields if n not in meta)
