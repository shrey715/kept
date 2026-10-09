-- Account, payroll and cash-flow features per (case, as_of), point in time (Track D).
-- History features (dpd, utilisation, cash flow) read account_points known at as_of, the same way
-- for serving and training. Payroll delay and pay change come from the dated monthly salary feed
-- (salary_credit_history, employer credits only), read as of the earlier of as_of and the feed's last
-- complete month, the same way for serving and training, so the model learns from pay shocks without
-- a leak. Spare cash needs the deposit snapshot's spend fields: serving only, null in training.
{% set training = var('training_spine', false) %}
with spine as (
    select s.case_id, s.as_of, cast(s.as_of as date) as d, x.golden_customer_id
    from {{ ref('feature_spine') }} s
    join {{ ref('identity_crosswalk') }} x
        on x.source_system = 'collections' and x.source_key = s.crm_customer_id and x.valid_to is null
),
known as (
    select s.case_id, s.as_of, s.d, p.*
    from spine s
    join {{ ref('account_points') }} p on p.golden_customer_id = s.golden_customer_id and p.point_date <= s.d
),
dpd_now as (  -- each card/loan account's latest dpd, aged by the days since a month-end within a month
    -- ponytail: assumes no payment since that month-end; daily balances would make this exact
    select case_id, as_of, account_id,
           arg_max(dpd, point_date) + case
               when arg_max(dpd, point_date) > 0 and any_value(d) - max(point_date) <= 31
                   then any_value(d) - max(point_date) else 0 end as dpd
    from known
    where kind in ('card', 'loan') and dpd is not null
    group by case_id, as_of, account_id
),
delinquency as (
    select d.case_id, d.as_of, max(d.dpd) as max_dpd
    from dpd_now d
    group by d.case_id, d.as_of
),
times_30 as (  -- month-ends in the last 12 months where any account was 30+ dpd
    select case_id, as_of, count(distinct point_date) as times_30plus_dpd_12m
    from known
    where month_end and kind in ('card', 'loan') and dpd >= 30 and point_date > d - interval 12 month
    group by case_id, as_of
),
monthly as (  -- per month-end in the last 12 months: total net cash flow, mean card utilisation
    select case_id, as_of, point_date,
           date_diff('month', date '2000-01-01', point_date) as m,
           sum(net_cash_flow) filter (where kind = 'deposit') as net_cash_flow,
           avg(utilisation) filter (where kind = 'card') as utilisation
    from known
    where month_end and point_date > d - interval 12 month
    group by case_id, as_of, point_date
),
trends as (  -- least-squares slope per month; at least 3 months
    select case_id, as_of,
           -- rounded: regr_slope's float sums change in the last bits with row order, and a slope of
           -- 2e-15 vs -4e-16 sits either side of a tree split (scripts/invariance_test.py found 4 such cards)
           case when count(net_cash_flow) >= 3 then round(regr_slope(net_cash_flow, m), 9) end as cash_flow_trend,
           case when count(utilisation) >= 3 then round(regr_slope(utilisation, m), 9) end as card_utilisation_trend
    from monthly
    group by case_id, as_of
),
payroll_account as (  -- as gold's int_payroll: the deposit account with the latest payroll deposit
    select x.golden_customer_id,
           arg_max(a.deposit_account_id, a.last_payroll_date) as account_id,
           arg_max(a.snapshot_date, a.last_payroll_date) as snapshot_date,
           arg_max(a.expected_next_payroll_date, a.last_payroll_date) as next_payroll,
           arg_max(a.payroll_frequency_detected, a.last_payroll_date) as pay_frequency,
           arg_max(a.payroll_avg_amount_3m, a.last_payroll_date) as pay_avg_3m,  -- per payday
           arg_max(a.essential_spend_amount_mtd, a.last_payroll_date) as essentials,
           arg_max(a.other_lender_payment_amount_mtd, a.last_payroll_date) as other_lenders
    from {{ ref('deposit_accounts') }} a
    join {{ ref('identity_crosswalk') }} x
        on x.source_system = 'deposit' and x.source_key = a.src_customer_ref and x.valid_to is null
    where a.expected_next_payroll_date is not null
      and x.golden_customer_id in (select golden_customer_id from spine)
    group by x.golden_customer_id
),
housing as (
    select x.golden_customer_id, max(c.monthly_housing_cost) as monthly_housing_cost
    from {{ ref('customers') }} c
    join {{ ref('identity_crosswalk') }} x
        on x.source_system = 'crm' and x.source_key = c.crm_customer_id and x.valid_to is null
    where x.golden_customer_id in (select golden_customer_id from spine)
    group by x.golden_customer_id
),
salary as (  -- employer pay per deposit account and month, keyed to the golden customer
    select x.golden_customer_id, m.deposit_account_id as account_id,
           cast(m.credit_month || '-01' as date) as month_start, m.credit_count,
           m.credit_amount_total::double as amount, m.first_credit_date, m.last_credit_date
    from {{ ref('salary_credit_history') }} m
    join {{ ref('deposit_accounts') }} a on a.deposit_account_id = m.deposit_account_id
    join {{ ref('identity_crosswalk') }} x
        on x.source_system = 'deposit' and x.source_key = a.src_customer_ref and x.valid_to is null
    where m.employer_flag = 'Y' and x.golden_customer_id in (select golden_customer_id from spine)
),
salary_seen as (  -- per (case, as_of): the months known at h, the earlier of as_of and the feed's end
    select s.case_id, s.as_of, least(s.d, e.h) as h, p.*
    from spine s
    cross join (select max(last_day(month_start)) + 1 as h from salary) e
    join salary p on p.golden_customer_id = s.golden_customer_id
        and p.month_start < least(s.d, e.h) and p.month_start >= least(s.d, e.h) - interval 7 month
),
pay_account as (  -- the account with the most pay credits in the window
    select case_id, as_of, account_id
    from (select case_id, as_of, account_id, sum(credit_count) as n from salary_seen group by all)
    where n > 0
    qualify row_number() over (partition by case_id, as_of order by n desc, account_id) = 1
),
pay_months as (  -- complete months with pay, newest first (k = 1)
    select v.*, row_number() over (partition by v.case_id, v.as_of order by v.month_start desc) as k
    from salary_seen v join pay_account a using (case_id, as_of, account_id)
    where last_day(v.month_start) < v.h and v.credit_count > 0
),
pay_shock as (
    select case_id, as_of,
           -- latest month's pay per credit vs the three months before it, per credit (bank: "latest vs 3m average")
           max(amount / credit_count) filter (where k = 1)
               / nullif(sum(amount) filter (where k between 2 and 4)
                        / nullif(sum(credit_count) filter (where k between 2 and 4), 0), 0) - 1 as pay_change,
           avg(credit_count) filter (where k <= 3) as pays_per_month
    from pay_months
    group by case_id, as_of
),
last_pay as (  -- the last pay date known at h: a month's first and last credit dates are known once passed
    select v.case_id, v.as_of, any_value(v.h) as h,
           max(greatest(case when v.first_credit_date < v.h then v.first_credit_date end,
                        case when v.last_credit_date < v.h then v.last_credit_date end)) as paid
    from salary_seen v join pay_account a using (case_id, as_of, account_id)
    group by v.case_id, v.as_of
),
payroll_pit as (  -- bank's definition: days past the expected payday with no pay, after 2 days' tolerance
    select l.case_id, l.as_of,
           greatest(0, l.h - (l.paid + cast(round(30.4 / k.pays_per_month) as integer)) - 2) as payroll_delay_days,
           round(k.pay_change, 4) as pay_change_vs_3m_avg
    from last_pay l join pay_shock k using (case_id, as_of)
    where l.paid is not null
),
local_day as (  -- as_of's calendar date where the customer lives (kept.features.definitions)
    select s.case_id, s.as_of, s.golden_customer_id,
           -- ponytail: no time zone on the golden record -> Toronto, where most customers live
           cast(timezone(coalesce(g.time_zone, 'America/Toronto'), cast(s.as_of as timestamptz)) as date) as l
    from spine s
    left join {{ ref('c360_customer') }} g using (golden_customer_id)
)
select
    s.case_id,
    s.as_of,
    q.max_dpd,
    case when q.max_dpd is not null then coalesce(t.times_30plus_dpd_12m, 0) end as times_30plus_dpd_12m,
    -- days since entering the current dpd bucket: dpd past the bucket's first day (96% equal to
    -- collections_cases.bucket_entry_date on the open cases, without its look-ahead in training)
    case
        when q.max_dpd is null or q.max_dpd <= 0 then null
        when q.max_dpd <= 30 then q.max_dpd - 1
        when q.max_dpd <= 60 then q.max_dpd - 31
        when q.max_dpd <= 90 then q.max_dpd - 61
        when q.max_dpd <= 120 then q.max_dpd - 91
        else q.max_dpd - 121
    end as days_in_bucket,
    -- next payday on or after the local date, projected along the detected schedule (semi-monthly
    -- pays every 15 days in this data); an overdue expected date stays negative
    case
        when p.next_payroll is null then null
        when p.next_payroll < l.l then p.next_payroll - l.l
        when p.pay_frequency = 'weekly' then (p.next_payroll - l.l) % 7
        when p.pay_frequency = 'biweekly' then (p.next_payroll - l.l) % 14
        when p.pay_frequency = 'semi_monthly' then (p.next_payroll - l.l) % 15
        when p.pay_frequency = 'monthly' then cast(
            case when p.next_payroll - to_months(date_diff('month', l.l, p.next_payroll)) >= l.l
                 then p.next_payroll - to_months(date_diff('month', l.l, p.next_payroll))
                 else p.next_payroll - to_months(date_diff('month', l.l, p.next_payroll) - 1) end
            as date) - l.l
    end as days_to_next_payroll,
    case when p.pay_frequency in ('weekly', 'biweekly', 'semi_monthly', 'monthly', 'irregular')
         then p.pay_frequency end as pay_frequency,
    y.payroll_delay_days::integer as payroll_delay_days,
    y.pay_change_vs_3m_avg::double as pay_change_vs_3m_avg,
    {% if training %}
    null::decimal(14, 2) as estimated_monthly_spare_cash,
    {% else %}
    -- monthly pay (pay per payday x paydays a month) minus housing, essentials and other lenders
    case when p.snapshot_date <= s.d
         then p.pay_avg_3m * case p.pay_frequency when 'weekly' then 52 / 12 when 'biweekly' then 26 / 12
                                                 when 'semi_monthly' then 2 when 'monthly' then 1 end
              - coalesce(p.essentials, 0) - coalesce(p.other_lenders, 0)
              - coalesce(h.monthly_housing_cost, 0) end as estimated_monthly_spare_cash,
    {% endif %}
    r.cash_flow_trend,
    r.card_utilisation_trend
from spine s
join local_day l using (case_id, as_of)
left join delinquency q using (case_id, as_of)
left join times_30 t using (case_id, as_of)
left join trends r using (case_id, as_of)
left join payroll_account p on p.golden_customer_id = s.golden_customer_id
left join housing h on h.golden_customer_id = s.golden_customer_id
left join payroll_pit y using (case_id, as_of)
