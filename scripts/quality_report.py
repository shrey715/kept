# ruff: noqa: E501  (one-off generator: long SQL and prose strings)
"""Write the gate summary (data/exports/reports/quality_summary.md; the full deliverable 4 is QUALITY_REPORT.pdf): the gate result plus every data issue we found, how many
records it touched (counted now, from the warehouse) and what we did about it.

    uv run kept gate          # first: it writes the gate table this reads
    uv run python scripts/quality_report.py
"""

from __future__ import annotations

from datetime import UTC, datetime

import duckdb

from kept.common.db import connect
from kept.config import EXPORT_DIR, REPO_ROOT
from kept.contracts.data_contract import load_data_contract

OUT = REPO_ROOT / "data" / "exports" / "reports" / "quality_summary.md"  # the full report: QUALITY_REPORT.pdf
PROVINCES = "'AB','BC','MB','NB','NL','NS','NT','NU','ON','PE','QC','SK','YT'"

# (issue, where, SQL returning (records affected, records in the table), how we handled it)
ISSUES: list[tuple[str, str, str, str]] = [
    (
        "Agent notes with lost characters (U+FFFD)",
        "agent_notes.note_text",
        "select count(*) filter (where note_text like '%' || chr(65533) || '%'), count(*) from bronze.agent_notes",
        "Not recoverable: the original characters are gone. Left as is; the redactor and extractor read the "
        "surrounding words, which are intact.",
    ),
    (
        "CRM records deleted upstream (CDC) but still in the extract",
        "customers.is_deleted",
        "select count(*) filter (where lower(is_deleted) = 'true'), count(*) from bronze.customers",
        "Left out of silver (the current version is deleted); listed in quarantine.customers.",
    ),
    (
        "A customer with two CRM records",
        "customers (crm_customer_id)",
        "select count(*) - count(distinct golden_customer_id), count(*) from gold.identity_crosswalk "
        "where source_system = 'crm' and valid_to is null",
        "Linked by the same national ID, CRM's own duplicate pointer, or Splink (name, DOB, phone, postal "
        "code); one golden ID each. The count is CRM records beyond the first of each golden ID.",
    ),
    (
        "Card phone numbers masked in the source (519555xxx42)",
        "card_accounts.cardholder_phone_raw",
        "select count(*), (select count(*) from bronze.card_accounts) from quarantine.card_accounts "
        "where \"column\" = 'cardholder_phone_raw'",
        "Cannot be normalised to a phone number: left null in the cleaned column and listed in "
        "quarantine.card_accounts. Cards link on name, DOB and postal code instead.",
    ),
    (
        "CRM phone numbers cut to 9 digits",
        "customers.primary_phone_raw",
        "select count(*), (select count(*) from bronze.customers) from quarantine.customers "
        "where \"column\" = 'primary_phone_raw'",
        "Not a valid number: left null in the cleaned column, listed in quarantine.customers.",
    ),
    (
        "CRM date of birth keyed as DD/MM or MM/DD (cannot be told apart)",
        "customers.dob_raw",
        "select count(*) filter (where dob_raw like '%/%' and try_cast(split_part(dob_raw, '/', 1) as int) <= 12 "
        "and try_cast(split_part(dob_raw, '/', 2) as int) <= 12 and split_part(dob_raw, '/', 1) <> split_part(dob_raw, '/', 2)), "
        "count(*) from bronze.customers where dob_raw is not null",
        "Never guessed (reading every slash date day-first misreads 16% of them). CRM also holds a clean date_of_birth, "
        "which is used; the raw value only fills gaps when it is unambiguous. Cards, whose format is fixed "
        "DD-MM-YYYY, are read day-first.",
    ),
    (
        "month_end_date in three formats (ISO, DD/MM/YYYY, YYYYMMDD)",
        "account_monthly_snapshot.month_end_date",
        "select count(*) filter (where month_end_date not like '____-__-__'), count(*) "
        "from bronze.account_monthly_snapshot",
        "A plain date cast silently dropped these (1.25M values). Silver reads all three; a month-end day is "
        "always above 12, so the DD/MM form is unambiguous.",
    ),
    (
        "Province written as Ont., B.C., Alta., PQ, Quebec ...",
        "customers.province_code",
        f"select count(*) filter (where province_code not in ({PROVINCES})), count(province_code) from bronze.customers",
        "Mapped to the two-letter code (normalize_province); gold would otherwise break the contract.",
    ),
    (
        "A ratio too large for its declared type",
        "deposit_accounts.income_to_debt_service_ratio_est",
        "select count(*) filter (where income_to_debt_service_ratio_est is not null "
        "and try_cast(income_to_debt_service_ratio_est as decimal(8,4)) is null), "
        "count(income_to_debt_service_ratio_est) from bronze.deposit_accounts",
        "The data dictionary says decimal(8,4); values go above 9999.9999. Silver uses a wider decimal. The "
        "magnitudes look like a unit problem upstream: not used by any feature.",
    ),
    (
        "contact_history.channel renamed to channel_v2 on 26 Sep",
        "contact_history.channel, channel_v2",
        "select count(*) filter (where channel_v2 is not null), count(*) from bronze.contact_history",
        "Silver coalesces the two into channel (the dictionary name).",
    ),
    (
        "Loan borrower names in two orders (First Last / Last First)",
        "loan_accounts.borrower_name_raw",
        """with t as (select regexp_replace(lower(strip_accents(split_part(borrower_name_raw, ' ', 1))), '[^a-z]', '', 'g') a,
               regexp_replace(lower(strip_accents(string_split(borrower_name_raw, ' ')[-1])), '[^a-z]', '', 'g') b
               from bronze.loan_accounts where borrower_name_raw like '% %')
           select count(*) filter (where coalesce(la.last_share, .5) > coalesce(lb.last_share, .5)), count(*)
           from t left join silver.int_name_lexicon la on la.token = t.a left join silver.int_name_lexicon lb on lb.token = t.b""",
        "The token CRM uses more as a surname is the surname (silver.int_name_lexicon). Without it, loan "
        "names matched other systems 79% of the time; with it, 98%.",
    ),
    (
        "Autopay / pre-authorised-debit account at another bank (not one of our deposit accounts)",
        "card_accounts.autopay_source_account, loan_accounts.pad_source_account",
        """select (select count(*) from bronze.card_accounts c where autopay_source_account is not null
                   and autopay_source_account not in (select deposit_account_id from bronze.deposit_accounts))
                 + (select count(*) from bronze.loan_accounts l where pad_source_account is not null
                   and pad_source_account not in (select deposit_account_id from bronze.deposit_accounts)),
                (select count(autopay_source_account) from bronze.card_accounts)
                 + (select count(pad_source_account) from bronze.loan_accounts)""",
        "Ignored for linking: there is nothing at our bank to link to. Left untouched in silver.",
    ),
    (
        "National Do Not Call flag set",
        "customers.national_dncl_flag",
        "select count(*) filter (where national_dncl_flag::boolean), count(*) from silver.customers",
        "Never blocks collections contact (the list covers telemarketing, not collections). Internal "
        "do-not-call and cease flags do.",
    ),
    (
        "Delinquency buckets finer than the contract's top bucket (121-150, 151-180, 180+)",
        "collections_cases.current_bucket",
        "select count(*) filter (where current_bucket in ('121-150', '151-180', '180+')), count(*) "
        "from silver.collections_cases",
        "Silver keeps the source label. Gold derives its bucket from days past due, with one 121+ bucket "
        "(the shared contract).",
    ),
    (
        "Card cycles_delinquent far from days past due (cycles are not days)",
        "card_accounts.cycles_delinquent, dpd",
        "select count(*) filter (where cycles_delinquent > 0 and abs(dpd - 30 * cycles_delinquent) > 30), "
        "count(*) filter (where cycles_delinquent > 0) from silver.card_accounts",
        "Gold and features use dpd, never cycles_delinquent.",
    ),
    (
        "Contact rows whose case is not in collections_cases (orphans; the example contract allows < 1%)",
        "contact_history.case_id",
        "select count(*) filter (where case_id is not null and case_id not in (select case_id from silver.collections_cases)), "
        "count(case_id) from silver.contact_history",
        "Counted and kept in silver; nothing joins them to a case.",
    ),
    (
        "Duplicate primary keys in the source tables",
        "customers, contact_history, promises_to_pay, agent_notes",
        """select (select count(*) - count(distinct crm_customer_id) from bronze.customers)
                 + (select count(*) - count(distinct contact_id) from bronze.contact_history)
                 + (select count(*) - count(distinct ptp_id) from bronze.promises_to_pay)
                 + (select count(*) - count(distinct note_id) from bronze.agent_notes),
                (select count(*) from bronze.customers) + (select count(*) from bronze.contact_history)
                 + (select count(*) from bronze.promises_to_pay) + (select count(*) from bronze.agent_notes)""",
        "None found when this report was written (the count above is the proof).",
    ),
    (
        "Transactions cover a customer sample and 13 months only",
        "transactions",
        "select count(distinct account_id), (select count(*) from silver.deposit_accounts) from silver.transactions",
        "Missing stays missing: features from transactions are null, not 0, outside the sample.",
    ),
    (
        "Keys that no rule or model could link (singletons, or held apart)",
        "gold.c360_customer",
        "select count(*) filter (where match_review_status = 'unlinked'), count(*) from gold.c360_customer",
        "Each keeps its own golden ID with status 'unlinked'. 5,498 clusters were held (two national IDs, or "
        "more than 12 keys) and go to the steward queue.",
    ),
]


def _line(conn: duckdb.DuckDBPyConnection, issue: str, where: str, sql: str, handled: str) -> str:
    affected, total = conn.execute(sql).fetchone()  # type: ignore[misc]
    share = f" ({affected / total:.2%} of {total:,})" if total else ""
    return f"| {issue} | `{where}` | {affected:,}{share} | {handled} |"


def main() -> None:
    conn = connect(read_only=True)
    try:
        rows = [_line(conn, *issue) for issue in ISSUES]
    finally:
        conn.close()
    gate = (EXPORT_DIR / "quality" / "quality_report.md").read_text()
    gate_table = gate[gate.index("Gate:") :]
    contract = load_data_contract()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        "\n".join(
            [
                "# Data quality report",
                "",
                f"Contract: `kept-c360-customer` v{contract.version}. Written {datetime.now(UTC):%Y-%m-%d %H:%M} UTC from the "
                "warehouse by `scripts/quality_report.py`: the record counts are queried; the few match-quality "
                "figures in the handling column (79% to 98%, 5,498 held clusters) are from Track A's checks, "
                "recorded in `docs/team/tracks/Track_A.md`.",
                "",
                "## 1. The gate on the golden record",
                "",
                "The five contract rules (Q1-Q5), plus the hardship-text and review-precision checks, run on "
                "the real gold table by `kept gate`:",
                "",
                gate_table.strip(),
                "",
                "## 2. Issues found in the source data",
                "",
                "| Issue | Where | Records affected | How we handled it |",
                "|---|---|---|---|",
                *rows,
                "",
                "## 3. What the cleaning rules are",
                "",
                "Every rule is a tested function in `kept.data.clean` / `kept.data.traps` (names, dates, phones, "
                "postal codes, provinces, snapshots, SCD2, schema drift). Values a rule cannot read are never "
                "guessed: they are left null in the cleaned column and listed in `quarantine.<table>` with the "
                "reason.",
                "",
                "## 4. What we do not know",
                "",
                "- **Matching precision against ground truth.** The organisers gave no ground-truth IDs. We "
                "report instead: Splink re-finds 99.9% of the exact links; no auto-linked cluster holds two "
                "national IDs; a steward reviews a random sample of 300 predicted links (target 98%).",
                "- **Notes and transcripts** are read by a model trained on the public labels; its accuracy is "
                "Track C's F1 gate, not measured here.",
                "",
            ]
        )
    )
    print(f"{OUT} ({len(rows)} issues)")


if __name__ == "__main__":
    main()
