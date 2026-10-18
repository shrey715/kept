{{ config(enabled=var('training_spine', false)) }}
-- Context at each training decision (training only): what the bank knew about the case just before it decided. These explain who the bank
-- contacts (so they are confounders) and who a contact changes (so they are effect modifiers). Strictly before decision_at, so a decision's
-- own contact never counts. Per case (contacts) or per customer (promises, payments), like the label sources.
with d as (
    select decision_id, case_id, crm_customer_id, decision_at from {{ ref('training_rows') }}
    union all
    select decision_id, case_id, crm_customer_id, decision_at from {{ ref('training_weeks') }}
),
out as (
    select case_id, contact_ts_utc, coalesce(rpc_flag, false) as rpc, coalesce(ptp_made_flag, false) as ptp_made
    from {{ ref('contact_history') }} where direction = 'outbound'
),
agg as (
    select d.decision_id,
        count(*) filter (where o.contact_ts_utc >= d.decision_at - interval 7 day) as n_out_7d,
        count(*) as n_out_30d,
        count(*) filter (where o.rpc) as n_rpc_30d,
        epoch(min(d.decision_at) - max(o.contact_ts_utc)) / 86400.0 as days_since_contact,
        arg_max(o.rpc, o.contact_ts_utc) as last_rpc,
        arg_max(o.ptp_made, o.contact_ts_utc) as last_ptp_made
    from d join out o on o.case_id = d.case_id and o.contact_ts_utc < d.decision_at
        and o.contact_ts_utc >= d.decision_at - interval 30 day
    group by d.decision_id
),
pend as (  -- open at the decision: made before it and not resolved before it
    select d.decision_id, true as pending_ptp, min(p.ptp_due_date) - min(cast(d.decision_at as date)) as ptp_due_in_days
    from d join {{ ref('promises_to_pay') }} p on p.crm_customer_id = d.crm_customer_id
        and p.ptp_created_ts < d.decision_at and (p.status_ts is null or p.status_ts >= d.decision_at)
    group by d.decision_id
),
paid_prev as (  -- a payment in the previous 7 days: a contact flag, or a promise paid
    select d.decision_id from d join {{ ref('contact_history') }} h on h.crm_customer_id = d.crm_customer_id
        and (h.payment_taken_flag or h.link_payment_flag or h.app_payment_after_contact_flag)
        and h.contact_ts_utc < d.decision_at and h.contact_ts_utc >= d.decision_at - interval 7 day
    union
    select d.decision_id from d join {{ ref('promises_to_pay') }} p on p.crm_customer_id = d.crm_customer_id
        and p.ptp_status in ('kept', 'partially_kept')
        and cast(p.paid_date as timestamp) + interval 12 hour < d.decision_at
        and cast(p.paid_date as timestamp) + interval 12 hour >= d.decision_at - interval 7 day
)
select d.decision_id, d.case_id, d.decision_at,
    coalesce(p.pending_ptp, false) as pending_ptp,
    p.ptp_due_in_days,
    coalesce(a.n_out_7d, 0) as n_out_7d,
    coalesce(a.n_out_30d, 0) as n_out_30d,
    coalesce(a.n_rpc_30d, 0) as n_rpc_30d,
    a.days_since_contact,
    a.last_rpc,
    a.last_ptp_made,
    d.decision_id in (select decision_id from paid_prev) as paid_prev7,
    dayofweek(d.decision_at) as weekday
from d
left join agg a using (decision_id)
left join pend p using (decision_id)
