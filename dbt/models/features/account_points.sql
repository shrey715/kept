-- Account history per golden customer on the feature spine (Track D), one row per (account, date).
-- Each account has one snapshot row in silver plus twelve monthly columns; m{k} is the month-end k
-- months before the snapshot's month (data dictionary: "month-end -1"). Unpacked here so features
-- can be read point in time: a point is known at as_of when point_date <= the as_of date.
with customers as (
    select distinct x.golden_customer_id
    from {{ ref('feature_spine') }} s
    join {{ ref('identity_crosswalk') }} x
        on x.source_system = 'collections' and x.source_key = s.crm_customer_id and x.valid_to is null
),
keys as (
    select x.golden_customer_id, x.source_system, x.source_key
    from {{ ref('identity_crosswalk') }} x
    join customers using (golden_customer_id)
    where x.valid_to is null and x.source_system in ('card', 'loan', 'deposit')
),
accounts as (
    select k.golden_customer_id, 'card' as kind, a.card_account_id as account_id, a.snapshot_date,
           a.dpd, a.utilisation, null::double as net_cash_flow,
           {{ month_columns('a.dpd') }} as dpd_m, {{ month_columns('a.utilisation') }} as utilisation_m,
           null::double[] as net_cash_flow_m
    from {{ ref('card_accounts') }} a
    join keys k on k.source_system = 'card' and k.source_key = a.src_customer_ref
    union all
    select k.golden_customer_id, 'loan', a.loan_id, a.snapshot_date, a.dpd, null, null,
           {{ month_columns('a.dpd') }}, null, null
    from {{ ref('loan_accounts') }} a
    join keys k on k.source_system = 'loan' and k.source_key = a.src_customer_ref
    union all
    -- the snapshot's month-to-date cash flow is a partial month: trends use month-ends only
    select k.golden_customer_id, 'deposit', a.deposit_account_id, a.snapshot_date, null, null, null,
           null, null, {{ month_columns('a.net_cash_flow') }}
    from {{ ref('deposit_accounts') }} a
    join keys k on k.source_system = 'deposit' and k.source_key = a.src_customer_ref
)
select golden_customer_id, kind, account_id, snapshot_date as point_date, false as month_end,
       dpd, utilisation::double as utilisation, net_cash_flow
from accounts
union all
select a.golden_customer_id, a.kind, a.account_id,
       last_day(a.snapshot_date - to_months(k.k)) as point_date, true as month_end,
       a.dpd_m[k.k], a.utilisation_m[k.k]::double, a.net_cash_flow_m[k.k]::double
from accounts a
cross join (select unnest(range(1, 13)) as k) k
