"""dbt hardship.cashflow_observations fires exactly where the Python cash-flow rule fires
(integration: needs a built warehouse with silver.deposit_accounts and the model)."""

from __future__ import annotations

from datetime import date

import pytest

from kept.config import WAREHOUSE_PATH
from kept.hardship.cashflow_rule import cash_flow_hardship, new_ei_deposit

pytestmark = pytest.mark.integration
AS_OF = date(2026, 9, 28)


def test_sql_matches_python_rule() -> None:
    duckdb = pytest.importorskip("duckdb")
    if not WAREHOUSE_PATH.exists():
        pytest.skip("no warehouse")
    c = duckdb.connect(str(WAREHOUSE_PATH), read_only=True)
    try:
        c.execute("select 1 from hardship.cashflow_observations limit 1")
    except duckdb.Error:
        pytest.skip("hardship.cashflow_observations not built")
    rows = c.execute(
        """select d.src_customer_ref, d.payroll_delay_days, d.payroll_amount_change_pct, d.ei_deposit_flag,
                  d.ei_first_deposit_date, x.golden_customer_id
           from silver.deposit_accounts d
           join silver.int_crosswalk x on x.source_system = 'deposit' and x.source_key = d.src_customer_ref
                and x.valid_to is null
           where d.payroll_deposit_flag and d.snapshot_date between ? - interval 35 day and ?""",
        [AS_OF, AS_OF],
    ).fetchall()
    sql_fired = {
        g for (g,) in c.execute("select golden_customer_id from hardship.cashflow_observations").fetchall()
    }
    c.close()
    assert rows
    py_fired = {
        golden
        for _, delay, change, ei_flag, ei_first, golden in rows
        if cash_flow_hardship(
            payroll_delay_days=delay,
            pay_change_vs_3m_avg=float(change) if change is not None else None,
            new_ei_deposit=new_ei_deposit(
                ei_deposit_flag=ei_flag, ei_first_deposit_date=ei_first, as_of=AS_OF
            ),
        )
    }
    assert py_fired == sql_fired  # same golden customers, both directions
