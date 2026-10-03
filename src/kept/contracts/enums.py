"""Enumerations shared by every layer. Values are the strings stored in DuckDB."""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType
from typing import Final


class Action(StrEnum):
    """The eight NBA actions (design §6)."""

    WAIT = "wait"
    EMAIL = "email"
    PUSH = "push"
    SMS_PAYMENT_LINK = "sms_payment_link"
    CALL = "call"
    PROMISE_REQUEST = "promise_request"
    PAYMENT_PLAN = "payment_plan"
    HARDSHIP_REVIEW = "hardship_review"


class Channel(StrEnum):
    CALL = "call"
    SMS = "sms"
    EMAIL = "email"
    PUSH = "push"


# Which consent each action needs. WAIT contacts nobody.
# v0 assumption: promise requests, plans and hardship reviews happen on a call.
ACTION_CHANNEL: Final = MappingProxyType(
    {
        Action.WAIT: None,
        Action.EMAIL: Channel.EMAIL,
        Action.PUSH: Channel.PUSH,
        Action.SMS_PAYMENT_LINK: Channel.SMS,
        Action.CALL: Channel.CALL,
        Action.PROMISE_REQUEST: Channel.CALL,
        Action.PAYMENT_PLAN: Channel.CALL,
        Action.HARDSHIP_REVIEW: Channel.CALL,
    }
)

# Hardship override (design §6.3): check-in call, hardship review, payment plan or wait.
HARDSHIP_ALLOWED_ACTIONS: Final = frozenset(
    {Action.CALL, Action.HARDSHIP_REVIEW, Action.PAYMENT_PLAN, Action.WAIT}
)


class ReleaseTier(StrEnum):
    """Who may release a proposal (design §6 tier table). Order = precedence."""

    BLOCKED = "blocked"  # any hard stop; nobody (compliance may override with a reason)
    RED = "red"  # hardship, reductions, settlement, LLM-vs-agent disagreement
    AMBER = "amber"  # calls, promises, plans, close calls between top two
    GREEN = "green"  # template reminders and SMS links; team lead batch approval


class HardStop(StrEnum):
    CEASE = "cease"
    INSOLVENCY = "insolvency"
    BANKRUPTCY = "bankruptcy"
    DECEASED = "deceased"


class HardshipStatus(StrEnum):
    """Combined status on the golden record. Only a person can set CONFIRMED or clear it."""

    NONE = "none"
    POSSIBLE = "possible"
    CONFIRMED = "confirmed"


class HardshipSignal(StrEnum):
    """What text extraction returns for one note or call (feature table, design §5)."""

    NONE = "none"
    POSSIBLE = "possible"
    CLEAR = "clear"


class HardshipSource(StrEnum):
    """collections_cases.hardship_source uses agent_coded / customer_form / model / llm_flag;
    we add account programmes (card/loan hardship_program_flag) and our cash-flow rule."""

    AGENT = "agent"  # agent_coded, contact_history.hardship_mentioned_flag
    CUSTOMER_FORM = "customer_form"
    ACCOUNT_PROGRAMME = "account_programme"
    MODEL = "model"  # existing bank model flag
    LLM = "llm"  # llm_flag, or our text extraction
    CASH_FLOW = "cash_flow"


class MatchReviewStatus(StrEnum):
    """match_review_status on the golden record (data contract)."""

    AUTO = "auto"
    STEWARD_APPROVED = "steward_approved"
    UNLINKED = "unlinked"


class MatchRoute(StrEnum):
    """Where a scored candidate pair goes."""

    AUTO_LINK = "auto_link"  # >= 0.95
    STEWARD_REVIEW = "steward_review"  # 0.80-0.95, or a cluster safety rule fired
    PROVISIONAL = "provisional"  # < 0.80, keeps a provisional ID


class DpdBucket(StrEnum):
    """Days-past-due buckets. TBC: confirm bucket edges with the organisers."""

    CURRENT = "current"  # 0
    B1_30 = "1-30"
    B31_60 = "31-60"
    B61_90 = "61-90"
    B91_120 = "91-120"
    B121_PLUS = "121+"


class PayrollFrequency(StrEnum):
    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    SEMI_MONTHLY = "semi_monthly"
    MONTHLY = "monthly"
    IRREGULAR = "irregular"
    UNKNOWN = "unknown"


class SourceSystem(StrEnum):
    """Each product system uses its own customer key."""

    CRM = "crm"
    CARD = "card"
    LOAN = "loan"
    DEPOSIT = "deposit"
    COLLECTIONS = "collections"
    BUREAU = "bureau"


class Role(StrEnum):
    AGENT = "agent"
    HARDSHIP_SPECIALIST = "hardship_specialist"
    TEAM_LEAD = "team_lead"
    ANALYST = "analyst"
    COMPLIANCE = "compliance"
    DATA_STEWARD = "data_steward"
    ENGINEER = "engineer"


class Sensitivity(StrEnum):
    """Column sensitivity classes used in the data contract."""

    INTERNAL = "internal"
    DIRECT_PII = "direct_pii"
    QUASI_IDENTIFIER = "quasi_identifier"
    SENSITIVE = "sensitive"
    PROTECTED = "protected"  # only in c360_restricted, compliance only


class ReviewDecision(StrEnum):
    """What a person does with a proposal on the card."""

    ACCEPT = "accept"
    EDIT = "edit"  # edit amount or date
    ALTERNATIVE = "alternative"  # pick another action
    OVERRIDE = "override"  # reason required
    REJECT = "reject"
