{{ config(schema='hardship', materialized='table') }}
-- Cash-flow hardship observations (Track C), one row per golden customer whose current deposit
-- account fires kept.hardship.cashflow_rule: payroll >= 5 days late (net of the 2-day tolerance),
-- pay down >= 20% vs the 3-month average, or EI deposits that started within 60 days of as_of.
-- Same thresholds as CashFlowRuleConfig; tests/hardship/test_cashflow_sql.py checks this SQL against
-- the Python rule. Signal is always POSSIBLE: cash flow is an inference and only ever protects.
-- Columns match silver.int_hardship_observations (A) so it unions in as one more source (Q6).
with current_accounts as (
    select src_customer_ref, snapshot_date, payroll_delay_days, payroll_amount_change_pct,
           ei_deposit_flag, ei_first_deposit_date
    from {{ ref('deposit_accounts') }}
    where snapshot_date >= date '{{ var("as_of_date", "2026-09-28") }}' - interval 35 day  -- current snapshot
      and snapshot_date <= date '{{ var("as_of_date", "2026-09-28") }}'
      and payroll_deposit_flag
), fired as (
    select * from current_accounts
    where payroll_delay_days >= 5
       or payroll_amount_change_pct <= -0.20
       or (ei_deposit_flag and (ei_first_deposit_date is null
           or date '{{ var("as_of_date", "2026-09-28") }}' - ei_first_deposit_date between 0 and 60))
)
select x.golden_customer_id,
       'cash_flow'                        as source,
       'possible'                         as signal,
       max(cast(f.snapshot_date as timestamp)) as observed_at,
       null::varchar                      as confirmed_by,
       null::varchar                      as cleared_by
from fired f
join {{ source('identity', 'int_crosswalk') }} x
    on x.source_system = 'deposit' and x.source_key = f.src_customer_ref and x.valid_to is null
group by x.golden_customer_id
