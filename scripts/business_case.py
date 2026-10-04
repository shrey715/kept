# ruff: noqa: E501  (report prose)
"""The dollar case for Kept sizing, from the release's own history (deliverable support for the deck).

    uv run python scripts/business_case.py      # writes docs/reports/business_case.md

Resolved promises by days between the customer's last salary credit and the due date (scripts/
payday_timing.py), then: if every promise now due 3+ days after payday were dated 0-2 days after it (what
Kept sizing does), and the paid share of those promises moved to the 0-2-day group's, how much more of the
promised money would be paid in a year? Descriptive, not causal: the gap may partly reflect who gets which
due date. Reads data/raw only, so it runs next to `kept serve`.
"""

from __future__ import annotations

import duckdb

from kept.config import REPO_ROOT

PROMISES = "read_csv_auto('data/raw/promises_to_pay.csv', all_varchar=true)"
SALARY = "read_parquet('data/raw/salary_credit_history/*/*.parquet', hive_partitioning=true)"
YEAR = "due > date '2025-09-28' and due <= date '2026-09-28'"  # the 12 months to the release snapshot

SQL = f"""
with pay as (
    select distinct crm_customer_id, unnest([first_credit_date, last_credit_date]) as d
    from {SALARY} where crm_customer_id is not null
), pr as (
    select ptp_id, crm_customer_id, try_cast(ptp_due_date as date) as due, ptp_status,
           try_cast(ptp_amount as double) as amt, try_cast(amount_paid_against as double) as paid
    from {PROMISES} where ptp_status in ('kept', 'partially_kept', 'broken')
), last_pay as (
    select pr.ptp_id, max(pay.d) as lp
    from pr join pay on pay.crm_customer_id = pr.crm_customer_id and pay.d between pr.due - 40 and pr.due
    group by pr.ptp_id
)
select case when lp is null then 'unknown' when due - lp <= 2 then '0-2' when due - lp <= 7 then '3-7'
            else '8+' end as timing,
       count(*) as n, sum(amt) as promised, sum(paid) as paid,
       count(*) filter (where {YEAR}) as n_year, coalesce(sum(amt) filter (where {YEAR}), 0) as promised_year
from pr left join last_pay using (ptp_id) group by 1
"""


def main() -> None:
    con = duckdb.connect()
    con.execute("set memory_limit = '12GB'")
    g = {t: (n, amt, paid, ny, ay) for t, n, amt, paid, ny, ay in con.execute(SQL).fetchall()}
    rate = {t: g[t][2] / g[t][1] for t in ("0-2", "3-7", "8+")}
    seen = sum(g[t][1] for t in ("0-2", "3-7", "8+"))  # promised $ where the payday is known
    share = {t: g[t][1] / seen for t in ("3-7", "8+")}  # of that money, how much falls 3-7 / 8+ days after
    year = sum(v[4] for v in g.values())  # every resolved promise due in the 12 months, $ promised
    gain = {t: year * share[t] * (rate["0-2"] - rate[t]) for t in ("3-7", "8+")}
    total = sum(gain.values())
    lines = [
        "# Business case: promises dated to payday",
        "",
        "From the release's own history (`scripts/business_case.py`; timing from `scripts/payday_timing.py`).",
        "Descriptive, not causal: the gap may partly reflect who gets which due date. The 5% hold-out measures",
        "the real effect after launch.",
        "",
        "| promise due | promises | share of promised money paid |",
        "|---|---|---|",
        *(f"| {t} days after payday | {g[t][0]:,} | {rate[t]:.1%} |" for t in ("0-2", "3-7", "8+")),
        "",
        f"- Resolved promises due in the 12 months to 28 Sep 2026: **${year:,.0f}** promised.",
        f"- Where the payday is known, {share['3-7']:.0%} of the promised money fell 3-7 days after payday and "
        f"{share['8+']:.0%} 8+ days after.",
        f"- Kept dates promises 1-2 days after payday. If those promises were paid like the 0-2-day group: "
        f"**+${total:,.0f} a year** (${gain['8+']:,.0f} from the 8+ day group, ${gain['3-7']:,.0f} from 3-7),"
        f" {total / year:.1%} more of the promised money.",
        "",
        "Not counted: fewer wasted contacts from uplift targeting (Qini 0.0073 vs 0.0017 for calls) and lower",
        "roll rate, both measured on the hold-out after launch.",
    ]
    out = REPO_ROOT / "docs" / "reports" / "business_case.md"
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
