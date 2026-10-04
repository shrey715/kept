# ruff: noqa: E501  (report SQL)
"""Numbers for the business case's later sections (issues #72 #74 #75 #76 #78).

    uv run python scripts/business_extras.py

Reads the raw release files and the scored cards export (like scripts/business_case.py, but a 3 GB
DuckDB cap so it runs on a laptop) and writes data/exports/reports/business_extras.json:
  * payday: kept rate and money paid when a promise falls due 1-2 days before the NEXT salary
    deposit, next to 0-2 days after the last one (#72)
  * compliance: the current strategy's own recorded out-of-hours contacts and 7-day cap breaches (#74)
  * workload: Red cards for customers already on a running hardship plan (#75)
  * power: months of hold-out needed to see a 1 or 2 point drop in 30-day roll rate (#76)
  * roll_value: charge-offs avoided per year at 0.5 / 1 / 2 points (#78)
"""

from __future__ import annotations

import glob
import json
import math
import os
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[1]
RAW = REPO / "data" / "raw"
CASES = f"read_csv('{RAW / 'collections_cases.csv'}', header=true, all_varchar=true)"
PROMISES = f"read_csv('{RAW / 'promises_to_pay.csv'}', header=true, all_varchar=true)"
SALARY = f"read_parquet('{RAW / 'salary_credit_history'}/*/*.parquet', hive_partitioning=true)"
SNAPSHOT = "2026-09-28"
ROLL_RATE, CHARGEOFF_SHARE, AVG_CHARGEOFF = 0.488, 0.025, 12_523  # business case §1 (measured there)


def power_months(entrants_per_month: float, share: float, drop: float, p: float = ROLL_RATE) -> float:
    """Months of new 1-30 DPD cases until a hold-out of `share` detects a roll-rate `drop`
    (two-sided two-proportion z-test, alpha 0.05, power 0.8, unequal arms)."""
    za, zb = 1.959964, 0.841621
    k = (1 - share) / share  # treated cases per hold-out case
    p2 = p - drop
    pbar = (p + k * p2) / (1 + k)
    n_control = (
        za * math.sqrt(pbar * (1 - pbar) * (1 + 1 / k)) + zb * math.sqrt(p * (1 - p) + p2 * (1 - p2) / k)
    ) ** 2 / drop**2
    return n_control / (entrants_per_month * share)


def collect() -> dict[str, object]:
    con = duckdb.connect()
    con.execute("set memory_limit = '3GB'; set threads = 2; set enable_progress_bar = false")
    payday = con.execute(f"""
        with pay as (select distinct crm_customer_id, unnest([first_credit_date, last_credit_date]) as d
                     from {SALARY} where crm_customer_id is not null),
        pr as (select ptp_id, crm_customer_id, try_cast(ptp_due_date as date) as due, ptp_status,
                      try_cast(ptp_amount as double) as amt, try_cast(amount_paid_against as double) as paid
               from {PROMISES} where ptp_status in ('kept', 'partially_kept', 'broken')),
        nxt as (select pr.ptp_id, min(pay.d) as np from pr join pay on pay.crm_customer_id = pr.crm_customer_id
                and pay.d > pr.due and pay.d <= pr.due + 40 group by 1),
        lst as (select pr.ptp_id, max(pay.d) as lp from pr join pay on pay.crm_customer_id = pr.crm_customer_id
                and pay.d between pr.due - 40 and pr.due group by 1)
        select case when np - due <= 2 then 'before_next' when due - lp <= 2 then 'after_0_2' end as b,
               count(*), avg((ptp_status = 'kept')::int), sum(paid) / sum(amt)
        from pr join lst using (ptp_id) join nxt using (ptp_id)
        where np - due <= 2 or due - lp <= 2 group by 1""").fetchall()
    out_of_hours, cap_breaches, cases_breached = con.execute(
        f"select sum(try_cast(out_of_hours_contact_count as int)), sum(try_cast(contact_cap_breach_count as int)),"
        f" count(*) filter (where try_cast(contact_cap_breach_count as int) > 0) from {CASES}"
    ).fetchone()  # type: ignore[misc]
    card_file = max(
        glob.glob(str(REPO / "data" / "exports" / "nba_cards" / "*.parquet")), key=os.path.getmtime
    )
    red, on_plan = con.execute(f"""
        select count(*), count(*) filter (where try_cast(c.hardship_plan_start as date) <= date '{SNAPSHOT}'
            and coalesce(try_cast(c.hardship_plan_end as date), date '9999-12-31') >= date '{SNAPSHOT}')
        from read_parquet('{card_file}') k join {CASES} c using (case_id) where k.tier = 'red'""").fetchone()  # type: ignore[misc]
    (entrants,) = con.execute(
        f"select count(*) from {CASES} where try_cast(entry_dpd as int) between 1 and 30"
        f" and try_cast(case_open_date as date) > date '{SNAPSHOT}' - interval 12 month"
    ).fetchone()  # type: ignore[misc]
    per_month = entrants / 12
    per_point = entrants * CHARGEOFF_SHARE * AVG_CHARGEOFF / 100  # one point of 30-day roll rate
    return {
        "payday": {b: {"promises": n, "kept": kept, "money_paid": money} for b, n, kept, money in payday},
        "compliance": {
            "out_of_hours_contacts": out_of_hours,
            "cap_breaches": cap_breaches,
            "cases_with_breach": cases_breached,
        },
        "workload": {"cards_file": Path(card_file).name, "red": red, "red_on_running_plan": on_plan},
        "power": {
            "entrants_per_month": round(per_month),
            "months": {
                f"{s:.0%} hold-out, {d} pt": round(power_months(per_month, s, d / 100), 1)
                for s in (0.05, 0.10, 0.20)
                for d in (1, 2)
            },
        },
        "roll_value": {f"{pts} pt": round(pts * per_point) for pts in (0.5, 1, 2)},
    }


def demo() -> None:
    """The power formula against a textbook case: 50% vs 45%, equal arms -> ~1,565 per arm."""
    k_equal_share = 0.5
    n = power_months(1.0, k_equal_share, 0.05, p=0.5) * k_equal_share
    assert 1_540 < n < 1_590, n


if __name__ == "__main__":
    demo()
    data = collect()
    out = REPO / "data" / "exports" / "reports" / "business_extras.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1, default=str))
    print(json.dumps(data, indent=1, default=str))
