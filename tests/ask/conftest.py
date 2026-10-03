"""Track B fixtures. The DataContract is built by hand so Track B never waits on
Track A's loader; the warehouse is a tiny in-memory DuckDB using the data
dictionary's table and column names (curated tables keep source names in silver)."""

from __future__ import annotations

from datetime import UTC, datetime

import duckdb
import pytest

from kept.ask.metrics import CertifiedQuery, MetricDefinition
from kept.contracts import Sensitivity, SqlPolicy
from kept.contracts.data_contract import ColumnSpec, DataContract

ALLOWED = frozenset({"gold.c360_customer", "silver.collections_cases", "silver.promises_to_pay"})
BLOCKED = frozenset(
    {
        "gender_code",
        "marital_status",
        "ccb_deposit_flag",  # protected
        "age",
        "postal_code",
        "date_of_birth",
        "salutation",
        "preferred_language",  # proxies
        "display_name",
        "primary_phone_e164",
        "email",
        "first_name",
        "last_name",
        "note_text",  # direct PII
    }
)
REFRESHED = datetime(2026, 9, 28, 10, 0, tzinfo=UTC)


TABLE_COLUMNS = {
    "gold.c360_customer": frozenset(
        {
            "golden_customer_id",
            "display_name",
            "primary_phone_e164",
            "email",
            "total_overdue",
            "assigned_agent_id",
        }
    ),
    "silver.collections_cases": frozenset(
        {
            "case_id",
            "primary_product",
            "entry_dpd",
            "dpd_at_day_30",
            "insolvency_hold_flag",
            "assigned_agent_id",
        }
    ),
    "silver.promises_to_pay": frozenset({"ptp_id", "case_id", "ptp_status", "ptp_amount"}),
}


@pytest.fixture
def policy() -> SqlPolicy:
    return SqlPolicy(
        allowed_tables=ALLOWED, blocked_columns=BLOCKED, table_columns=TABLE_COLUMNS, max_rows=100
    )


@pytest.fixture
def ask_contract() -> DataContract:
    def col(table: str, name: str, s: Sensitivity) -> ColumnSpec:
        return ColumnSpec(
            table=table, name=name, logical_type="string", sensitivity=s, required=False, description=""
        )

    c360 = "gold.c360_customer"
    return DataContract(
        version="1.0.0",
        columns=(
            col(c360, "golden_customer_id", Sensitivity.INTERNAL),
            col(c360, "display_name", Sensitivity.DIRECT_PII),
            col(c360, "primary_phone_e164", Sensitivity.DIRECT_PII),
            col(c360, "email", Sensitivity.DIRECT_PII),
            col(c360, "total_overdue", Sensitivity.INTERNAL),
            col("gold.c360_restricted", "gender_code", Sensitivity.PROTECTED),
            col("gold.c360_restricted", "marital_status", Sensitivity.PROTECTED),
            col("gold.c360_restricted", "ccb_deposit_flag", Sensitivity.PROTECTED),
        ),
        protected_attributes=frozenset(
            {
                "gender_code",
                "marital_status",
                "citizenship_status",
                "household_size",
                "dependants_count",
                "newcomer_program_flag",
                "newcomer_arrival_date",
                "accessibility_needs_flag",
                "accessibility_type",
                "vulnerability_type",
                "ccb_deposit_flag",
                "customer_accent_region",
            }
        ),
        proxy_attributes=frozenset(
            {
                "age",
                "age_band",
                "date_of_birth",
                "postal_code",
                "fsa",
                "salutation",
                "preferred_language",
                "ei_deposit_flag",
                "cpp_oas_deposit_flag",
            }
        ),
        restricted_tables=frozenset({"gold.c360_restricted"}),
        ask_allowed_tables=ALLOWED,
        direct_pii_columns=frozenset(
            {
                "customers.first_name",
                "customers.last_name",
                "customers.email",
                "agent_notes.note_text",
                "contact_history.sms_reply_text",
            }
        ),
        quasi_identifier_columns=frozenset({"customers.postal_code", "customers.age"}),
    )


@pytest.fixture
def ask_db() -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect()
    conn.execute("create schema gold")
    conn.execute("create schema silver")
    conn.execute("""
        create table gold.c360_customer as select * from (values
            ('G-000001', 'Jane Doe', '+14165550123', 'jane@example.com', 420.00, 'agent-7', TIMESTAMPTZ '2026-09-28 10:00:00+00'),
            ('G-000002', 'Raj Patel', '+16045550199', 'raj@example.com', 1300.00, 'agent-8', TIMESTAMPTZ '2026-09-28 10:00:00+00')
        ) t(golden_customer_id, display_name, primary_phone_e164, email, total_overdue, assigned_agent_id, refreshed_at)
    """)
    conn.execute("""
        create table silver.collections_cases as
        select 'CS-' || i as case_id,
               case when i % 2 = 0 then 'credit_card' else 'personal_loan' end as primary_product,
               (i % 30) + 1 as entry_dpd,
               case when i % 3 = 0 then 45 else 10 end as dpd_at_day_30,
               case when i % 5 = 0 then true else false end as insolvency_hold_flag,
               'agent-' || (i % 4) as assigned_agent_id
        from range(1, 61) r(i)
    """)
    conn.execute("""
        create table silver.promises_to_pay as
        select 'PTP-' || i as ptp_id, 'CS-' || i as case_id,
               case when i % 4 = 0 then 'broken' when i % 7 = 0 then 'partially_kept' else 'kept' end as ptp_status,
               100 + i as ptp_amount
        from range(1, 61) r(i)
    """)
    conn.execute(
        "create table gold.c360_restricted as select 'G-000001' as golden_customer_id, 'F' as gender_code"
    )
    return conn


@pytest.fixture
def metrics() -> dict[str, MetricDefinition]:
    def md(metric_id: str, certified: bool) -> MetricDefinition:
        return MetricDefinition(
            metric_id=metric_id,
            metric_name=metric_id.replace("_", " "),
            business_definition="Share of resolved promises that were kept in full",
            formula="count(kept) / count(resolved)",
            grain="promise",
            time_basis="promise due date",
            default_filters="exclude insolvency_hold",
            unit="ratio",
            good_direction="up",
            synonyms=("kept rate", "promise kept rate"),
            source_tables=("promises_to_pay", "collections_cases"),
            example_question="What is the promise kept rate for cards?",
            owner="Collections Strategy",
            certified_flag=certified,
        )

    return {"promise_kept_rate": md("promise_kept_rate", True), "draft_metric": md("draft_metric", False)}


@pytest.fixture
def certified_queries() -> dict[str, CertifiedQuery]:
    return {
        "promise_kept_rate": CertifiedQuery(
            metric_id="promise_kept_rate",
            sql_template=(
                "SELECT {group_by_select} avg(CASE WHEN p.ptp_status = 'kept' THEN 1.0 ELSE 0.0 END) AS kept_rate, "
                "count(*) AS n FROM silver.promises_to_pay p JOIN silver.collections_cases c USING (case_id) "
                "WHERE p.ptp_status IN ('kept', 'partially_kept', 'broken') {where} {group_by}"
            ),
            default_where=("NOT c.insolvency_hold_flag",),
            allowed_filters=frozenset({"primary_product"}),
            allowed_group_by=frozenset({"primary_product"}),
            date_column=None,
        ),
        # no query for draft_metric on purpose
    }
