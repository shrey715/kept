"""The feature registry: every feature, where it comes from, and who owns it.

This is the input to the protected-attribute CI test (design §9): a feature
whose lineage touches a protected attribute or a proxy fails the build.

source_columns are "<schema>.<table>.<column>" using the data dictionary's table and
column names (silver keeps source names). tests/contracts/test_data_dictionary.py
checks every one exists.

Point in time: collections_cases holds each case's LATEST state (as of the 28 Sep 2026
snapshot), not its state at a past decision. Training rows must take history from the
account snapshots (snapshot_date), promises (status_ts), and contact_history's at-contact
fields (dpd_at_contact, broken_ptp_count_at_contact, answer_rate_prior_30d,
contacts_prior_7d), never from the case row's current values.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class FeatureOrigin(StrEnum):
    SQL = "sql"  # dbt SQL, served by Feast
    COHORT = "cohort"  # cohort aggregates (groups of 50+)
    TEXT = "text"  # LLM / SetFit on notes and calls


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    name: str
    dtype: str
    origin: FeatureOrigin
    source_columns: tuple[str, ...]
    owner: str  # track letter
    description: str
    model_input: bool = True  # False: used by rules/sizing only, never by the uplift model


FEATURES: Final[tuple[FeatureSpec, ...]] = (
    # --- delinquency (account snapshots, collections cases)
    FeatureSpec(
        "max_dpd",
        "int",
        FeatureOrigin.SQL,
        ("silver.card_accounts.dpd", "silver.loan_accounts.dpd"),
        "D",
        "Max days past due across the customer's latest account snapshots (dpd, never cycles_delinquent)",
    ),
    FeatureSpec(
        "times_30plus_dpd_12m",
        "int",
        FeatureOrigin.SQL,
        ("silver.card_accounts.times_30dpd_12m", "silver.loan_accounts.times_30dpd_12m"),
        "D",
        "Times the customer reached 30+ DPD in the last 12 months",
    ),
    FeatureSpec(
        "days_in_bucket",
        "int",
        FeatureOrigin.SQL,
        ("silver.collections_cases.bucket_entry_date",),
        "D",
        "Days in the current DPD bucket",
    ),
    FeatureSpec(
        "balance_at_risk",
        "decimal",
        FeatureOrigin.SQL,
        ("silver.collections_cases.total_overdue",),
        "D",
        "Overdue balance at risk of rolling",
        model_input=False,
    ),
    # --- promises
    FeatureSpec(
        "broken_promises_90d",
        "int",
        FeatureOrigin.SQL,
        (
            "silver.promises_to_pay.ptp_status",
            "silver.promises_to_pay.ptp_due_date",
            "silver.promises_to_pay.status_ts",
        ),
        "D",
        "Promises due in the last 90 days with ptp_status broken",
    ),
    FeatureSpec(
        "kept_promise_ratio",
        "float",
        FeatureOrigin.SQL,
        ("silver.promises_to_pay.ptp_status", "silver.promises_to_pay.status_ts"),
        "D",
        "kept / (kept + partially_kept + broken); None if no resolved promises",
    ),
    # --- payroll (deposit accounts)
    FeatureSpec(
        "days_to_next_payroll",
        "int",
        FeatureOrigin.SQL,
        ("silver.deposit_accounts.expected_next_payroll_date",),
        "D",
        "Days from as_of to expected_next_payroll_date",
    ),
    FeatureSpec(
        "pay_frequency",
        "category",
        FeatureOrigin.SQL,
        ("silver.deposit_accounts.payroll_frequency_detected",),
        "D",
        "Detected payroll frequency",
    ),
    FeatureSpec(
        "payroll_delay_days",
        "int",
        FeatureOrigin.SQL,
        ("silver.deposit_accounts.payroll_delay_days",),
        "D",
        "Days since expected payroll with no credit (after the 2-day tolerance)",
    ),
    FeatureSpec(
        "pay_change_vs_3m_avg",
        "float",
        FeatureOrigin.SQL,
        ("silver.deposit_accounts.payroll_amount_change_pct",),
        "D",
        "Latest pay vs 3-month average as a fraction (-0.2672 = down 27%)",
    ),
    FeatureSpec(
        "estimated_monthly_spare_cash",
        "decimal",
        FeatureOrigin.SQL,
        (
            "silver.deposit_accounts.payroll_avg_amount_3m",
            "silver.deposit_accounts.essential_spend_amount_mtd",
            "silver.deposit_accounts.other_lender_payment_amount_mtd",
            "silver.customers.monthly_housing_cost",
        ),
        "D",
        "Pay minus rent/mortgage, essentials and other lenders; drives Kept sizing",
        model_input=False,
    ),
    # --- cash flow / utilisation
    FeatureSpec(
        "cash_flow_trend",
        "float",
        FeatureOrigin.SQL,
        ("silver.deposit_accounts.net_cash_flow_m01", "silver.deposit_accounts.net_cash_flow_mtd"),
        "D",
        "Slope of net monthly cash flow over net_cash_flow_m01..m12",
    ),
    FeatureSpec(
        "card_utilisation_trend",
        "float",
        FeatureOrigin.SQL,
        ("silver.card_accounts.utilisation", "silver.card_accounts.utilisation_m01"),
        "D",
        "Slope of card utilisation over utilisation_m01..m12",
    ),
    # --- contact history
    FeatureSpec(
        "answer_rate",
        "float",
        FeatureOrigin.SQL,
        ("silver.contact_history.dial_result", "silver.contact_history.channel"),
        "D",
        "Answered / attempted outbound calls",
    ),
    FeatureSpec(
        "answer_rate_after_18h",
        "float",
        FeatureOrigin.SQL,
        ("silver.contact_history.dial_result", "silver.contact_history.contact_hour_local"),
        "D",
        "Answer rate for calls placed at or after 18:00 customer-local time",
    ),
    FeatureSpec(
        "payment_link_usage",
        "float",
        FeatureOrigin.SQL,
        ("silver.contact_history.link_clicked_flag", "silver.contact_history.link_payment_flag"),
        "D",
        "Share of SMS payment links that led to a payment",
    ),
    FeatureSpec(
        "contacts_last_7d",
        "int",
        FeatureOrigin.SQL,
        ("silver.contact_history.contact_ts_utc",),
        "D",
        "Contacts in the rolling 7 days before as_of",
        model_input=False,
    ),
    # --- cohort (other, closed cases before as_of; groups of 50+)
    FeatureSpec(
        "cohort_recovery_rate",
        "float",
        FeatureOrigin.COHORT,
        (
            "silver.collections_cases.primary_product",
            "silver.collections_cases.current_bucket",
            "silver.collections_cases.cure_flag",
        ),
        "D",
        "Cure rate for product x bucket cohort (None if n < 50)",
    ),
    FeatureSpec(
        "cohort_kept_rate",
        "float",
        FeatureOrigin.COHORT,
        ("silver.promises_to_pay.ptp_status", "silver.collections_cases.primary_product"),
        "D",
        "Kept rate for product x bucket cohort (None if n < 50)",
    ),
    # --- text (agent notes, call transcripts)
    FeatureSpec(
        "hardship_signal",
        "category",
        FeatureOrigin.TEXT,
        ("silver.agent_notes.note_text", "silver.call_transcripts.turns"),
        "C",
        "none / possible / clear",
        model_input=False,
    ),
    FeatureSpec(
        "promise_intent",
        "bool",
        FeatureOrigin.TEXT,
        ("silver.call_transcripts.turns",),
        "C",
        "Customer stated an intent to pay",
        # always blank: the nightly's classifier only reads hardship (promise history reaches the model from
        # promises_to_pay). The live champion was trained with it, so it leaves at the next promoted retrain.
    ),
    FeatureSpec(
        "promised_date",
        "date",
        FeatureOrigin.TEXT,
        ("silver.call_transcripts.turns",),
        "C",
        "Date the customer promised",
        model_input=False,
    ),
    FeatureSpec(
        "promised_amount",
        "decimal",
        FeatureOrigin.TEXT,
        ("silver.call_transcripts.turns",),
        "C",
        "Amount the customer promised",
        model_input=False,
    ),
    FeatureSpec(
        "dispute_flag",
        "bool",
        FeatureOrigin.TEXT,
        ("silver.agent_notes.note_text", "silver.call_transcripts.turns"),
        "C",
        "Customer disputes the debt",
        model_input=False,
    ),
    FeatureSpec(
        "cease_request_flag",
        "bool",
        FeatureOrigin.TEXT,
        ("silver.agent_notes.note_text", "silver.call_transcripts.turns"),
        "C",
        "Customer asked us to stop contacting them; feeds hard stops",
        model_input=False,
    ),
    FeatureSpec(
        "third_party_present_flag",
        "bool",
        FeatureOrigin.TEXT,
        ("silver.agent_notes.note_text", "silver.call_transcripts.turns"),
        "C",
        "A third party was on the call; feeds hard stops",
        model_input=False,
    ),
)

# Outcomes and treatment assignment for the CURRENT decision: never a training input
# (design §5 deny-list). Column names from the data dictionary, plus our derived labels.
OUTCOME_DENY_LIST: Final = frozenset(
    {
        # labels we derive
        "paid_14d",
        "roll_forward_30d",
        # collections_cases outcomes
        "outcome",
        "outcome_date",
        "cure_flag",
        "cure_date",
        "days_to_cure",
        "roll_forward_count",
        "roll_back_count",
        "dpd_at_day_7",
        "dpd_at_day_14",
        "dpd_at_day_21",
        "dpd_at_day_30",
        "dpd_at_day_45",
        "dpd_at_day_60",
        "dpd_at_day_90",
        "overdue_at_day_7",
        "overdue_at_day_14",
        "overdue_at_day_21",
        "overdue_at_day_30",
        "overdue_at_day_45",
        "overdue_at_day_60",
        "overdue_at_day_90",
        "chargeoff_flag",
        "chargeoff_date",
        "chargeoff_amount",
        "recovered_post_chargeoff",
        "payments_since_open_amount",
        "payments_since_open_count",
        # treatment assignment and the incumbent strategy (treatment, not features)
        "test_cell",
        "assignment_method",
        "strategy_code",
        "treatment_path",
        "current_treatment",
        "nba_recommendation_last",
        "nba_accepted_flag",
        "human_override_flag",
        "override_reason",
    }
)

# Stated reasons trigger hardship handling only and never reach the model in any form (design §5).
STATED_REASON_FIELDS: Final = frozenset({"stated_reason", "hardship_reason", "broken_reason_agent_coded"})


def by_name() -> dict[str, FeatureSpec]:
    return {f.name: f for f in FEATURES}


def model_inputs() -> tuple[str, ...]:
    return tuple(f.name for f in FEATURES if f.model_input)
