# ruff: noqa: E501  (SQL strings)
"""Reviewed SQL for each certified metric (metric_definitions.csv). The LLM never writes these.

Reads silver tables with the data dictionary's names (K2). Tables used, for the Ask table list at G0:
collections_cases, promises_to_pay, agents, contact_history, account_monthly_snapshot,
card_accounts, loan_accounts, deposit_accounts. Values come back as ratios (0..1), CAD or days;
the narration turns ratios into percentages. Every query ends with `n`, the group size.

Date bounds are inclusive and apply to the metric's own date column (the roll-rate start snapshot,
the promise due date, the contact date ...). Each template starts its own `WHERE 1=1`, so {where}
can always append ` AND ...`.

Not certified here (no CertifiedQuery, so Ask falls back to lookup or a clarification):
  write_off_rate: the period bounds the numerator only; the denominator is all accounts, which one
    date column can't express.
"""

from __future__ import annotations

from kept.ask.metrics import CertifiedQuery

_RESOLVED = "ptp_status IN ('kept','partially_kept','broken')"
_PTP = """(SELECT p.ptp_status, p.ptp_due_date, p.ptp_channel, p.ptp_type, p.product, p.paid_date,
        p.amount_paid_against, p.prior_broken_ptp_count, c.queue, c.test_cell, c.assignment_method, c.province_code,
        coalesce(a.site, 'self_serve') AS site
      FROM silver.promises_to_pay p
      LEFT JOIN silver.collections_cases c ON c.case_id = p.case_id
      LEFT JOIN silver.agents a ON a.agent_id = p.agent_id) t"""
_PTP_COLS = frozenset(
    {"product", "ptp_channel", "ptp_type", "queue", "test_cell", "assignment_method", "province_code", "site"}
    | {"prior_broken_ptp_count"}
)
_CASE_COLS = frozenset({"primary_product", "queue", "province_code", "current_bucket"})
_CONTACT_COLS = frozenset({"contact_hour_local", "agent_site", "test_cell", "strategy_code", "day_of_week"})
_ACCOUNTS = """(SELECT 'card' AS product_family, product_code, dpd, dpd_bucket, snapshot_date
      FROM silver.card_accounts WHERE account_status IN ('active', 'blocked') AND dpd IS NOT NULL
      UNION ALL
      SELECT 'loan', product_code, dpd, dpd_bucket, snapshot_date
      FROM silver.loan_accounts WHERE NOT chargeoff_flag AND dpd IS NOT NULL) t"""
_NO_SYSTEM = ("channel <> 'system'",)
_BUCKETS = "['current','1-30','31-60','61-90','91-120','121-150','151-180','180+']"


def _ptp(
    metric_id: str, value: str, where: tuple[str, ...] = (_RESOLVED,), date: str = "ptp_due_date"
) -> CertifiedQuery:
    return CertifiedQuery(
        metric_id,
        f"SELECT {{group_by_select}} {value}, count(*) AS n FROM {_PTP} WHERE 1=1 {{where}} {{group_by}}",
        where,
        _PTP_COLS,
        _PTP_COLS,
        date,
    )


def _contacts(
    metric_id: str, value: str, where: tuple[str, ...], cols: frozenset[str] = _CONTACT_COLS
) -> CertifiedQuery:
    return CertifiedQuery(
        metric_id,
        f"SELECT {{group_by_select}} {value}, count(*) AS n FROM silver.contact_history WHERE 1=1 {{where}} {{group_by}}",
        where,
        cols,
        cols,
        "CAST(contact_ts_local AS DATE)",  # a timestamp <= date would drop the last day
    )


def _cases(metric_id: str, value: str, where: tuple[str, ...], date: str | None) -> CertifiedQuery:
    return CertifiedQuery(
        metric_id,
        f"SELECT {{group_by_select}} {value}, count(*) AS n FROM silver.collections_cases WHERE 1=1 {{where}} {{group_by}}",
        where,
        _CASE_COLS,
        _CASE_COLS,
        date,
    )


_HOLDS = ("NOT coalesce(insolvency_hold_flag, false)", "NOT coalesce(deceased_hold_flag, false)")
_CALLS = ("direction = 'outbound'", "channel = 'call'")

CERTIFIED_QUERIES: dict[str, CertifiedQuery] = {
    q.metric_id: q
    for q in (
        # Accounts in a delinquent bucket at one snapshot vs the same account's next snapshot.
        # date_from/date_to bound the START snapshot; a quarter-end to quarter-end roll is the
        # release's snapshot cadence. Buckets are computed from dpd, never read from dpd_bucket:
        # the source bucket disagrees with dpd on ~4% of rows (checked against the dev gold answer).
        # ponytail: insolvency holds are matched on primary_account_id only.
        CertifiedQuery(
            "roll_rate",
            f"""WITH s AS (
  SELECT account_id, product_type, month_end_date, dpd,
         lead(dpd) OVER (PARTITION BY account_id ORDER BY month_end_date) AS end_dpd
  FROM silver.account_monthly_snapshot m
  WHERE dpd IS NOT NULL AND NOT coalesce(write_off_flag, false)
    AND NOT EXISTS (SELECT 1 FROM silver.collections_cases c
                    WHERE c.primary_account_id = m.account_id AND c.insolvency_hold_flag)),
b AS (
  SELECT product_type, month_end_date, end_dpd, least(7, (dpd + 29) // 30) AS start_rank, least(7, (end_dpd + 29) // 30) AS end_rank,
         list_extract({_BUCKETS}, least(7, (dpd + 29) // 30) + 1) AS dpd_bucket
  FROM s)
SELECT {{group_by_select}} avg(CASE WHEN end_rank > start_rank THEN 1.0 ELSE 0.0 END) AS roll_rate, count(*) AS n
FROM b WHERE 1=1 {{where}} {{group_by}}""",
            ("start_rank > 0", "end_dpd IS NOT NULL"),
            frozenset({"product_type", "dpd_bucket"}),
            frozenset({"product_type", "dpd_bucket"}),
            "month_end_date",
        ),
        _cases(
            "cure_rate",
            "avg(CASE WHEN cure_flag THEN 1.0 ELSE 0.0 END) AS cure_rate",
            _HOLDS,
            "case_open_date",
        ),
        _ptp("promise_kept_rate", "avg(CASE WHEN ptp_status = 'kept' THEN 1.0 ELSE 0.0 END) AS kept_rate"),
        _ptp(
            "broken_promise_rate", "avg(CASE WHEN ptp_status = 'broken' THEN 1.0 ELSE 0.0 END) AS broken_rate"
        ),
        _contacts("rpc_rate", "avg(CASE WHEN rpc_flag THEN 1.0 ELSE 0.0 END) AS rpc_rate", _CALLS),
        _contacts(
            "ptp_rate", "avg(CASE WHEN ptp_made_flag THEN 1.0 ELSE 0.0 END) AS ptp_rate", ("rpc_flag",)
        ),
        _contacts(
            "cost_per_contact",
            "sum(contact_cost_cad) / count(*) AS cost_per_contact",
            _NO_SYSTEM,
            _CONTACT_COLS | {"channel"},
        ),
        _contacts(
            "cost_per_rpc",
            "sum(contact_cost_cad) / nullif(count(*) FILTER (WHERE rpc_flag), 0) AS cost_per_rpc",
            _NO_SYSTEM,
            _CONTACT_COLS | {"channel"},
        ),
        _ptp(
            "collected_amount",
            "sum(amount_paid_against) AS collected_amount",
            ("amount_paid_against > 0",),
            "paid_date",
        ),
        _cases(
            "hardship_rate",
            "avg(CASE WHEN hardship_flag THEN 1.0 ELSE 0.0 END) AS hardship_rate",
            (),
            "case_open_date",
        ),
        CertifiedQuery(
            "delinquency_rate",
            f"SELECT {{group_by_select}} avg(CASE WHEN dpd >= 1 THEN 1.0 ELSE 0.0 END) AS delinquency_rate, "
            f"count(*) AS n FROM {_ACCOUNTS} WHERE 1=1 {{where}} {{group_by}}",
            (),
            frozenset({"product_family", "product_code"}),  # not dpd_bucket: the metric is dpd >= 1, so a
            frozenset({"product_family", "product_code"}),  # rate per bucket is always 0% or 100%
            "snapshot_date",
        ),
        _cases("average_dpd", "avg(current_dpd) AS average_dpd", ("outcome IS NULL",), None),
        CertifiedQuery(
            "contact_attempts_per_case",
            """SELECT {group_by_select} avg(attempts) AS attempts_per_case, count(*) AS n
FROM (SELECT k.current_bucket, k.queue, k.primary_product, k.province_code,
        (SELECT count(*) FROM silver.contact_history h
         WHERE h.case_id = k.case_id AND h.direction = 'outbound' AND h.channel <> 'system') AS attempts
      FROM silver.collections_cases k WHERE k.outcome IS NULL) t
WHERE 1=1 {where} {group_by}""",
            (),
            _CASE_COLS,
            _CASE_COLS,
            None,
        ),
        CertifiedQuery(
            "payroll_delay_share",
            "SELECT {group_by_select} avg(CASE WHEN payroll_delay_days > 7 THEN 1.0 ELSE 0.0 END) AS payroll_delay_share, "
            "count(*) AS n FROM silver.deposit_accounts WHERE 1=1 {where} {group_by}",
            ("product_type = 'chequing'", "payroll_deposit_flag"),
            frozenset({"product_code"}),
            frozenset({"product_code"}),
            "snapshot_date",
        ),
    )
}
