"""Are promises timed to payday kept more often? Resolved promises (promises_to_pay) by days between the
customer's last salary credit (salary_credit_history: first and last credit date per month) and the due date.

    uv run python scripts/payday_timing.py

Reads the release's raw files, so it runs while `kept serve` holds the warehouse. Descriptive, not causal:
the numbers behind the card's "similar cases" line and the deck's business case.
"""

from __future__ import annotations

import duckdb

PROMISES = "read_csv_auto('data/raw/promises_to_pay.csv', all_varchar=true)"
SALARY = "read_parquet('data/raw/salary_credit_history/*/*.parquet', hive_partitioning=true)"

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
select case when lp is null then 'no salary seen'
            when due - lp <= 2 then 'due 0-2 days after payday'
            when due - lp <= 7 then 'due 3-7 days after payday'
            else 'due 8+ days after payday' end as timing,
       count(*) as promises,
       round(avg((ptp_status = 'kept')::int) * 100, 1) as kept_pct,
       round(sum(paid) / sum(amt) * 100, 1) as amount_paid_pct
from pr left join last_pay using (ptp_id)
group by 1 order by 1
"""


def main() -> None:
    con = duckdb.connect()
    con.execute("set memory_limit = '12GB'")
    print(f"{'timing':<28}{'promises':>10}{'kept %':>9}{'paid %':>9}")
    for timing, n, kept, paid in con.execute(SQL).fetchall():
        print(f"{timing:<28}{n:>10,}{kept:>9}{paid:>9}")


if __name__ == "__main__":
    main()
