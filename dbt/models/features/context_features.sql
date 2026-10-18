-- What the bank knew about the case at as_of (point in time, `<= as_of`): its recent outbound contacts and their outcomes,
-- an open promise, a payment in the last week, and the weekday. They say who the bank contacts and who a contact changes.
-- One row per (case, as_of) of the spine, so the nightly spine and the training spine (as_of a second before each
-- decision) read the same SQL. Contacts per case; promises and payments per customer, like the other features.
-- n_out_7d counts the same contacts as contacts_last_7d (a rule input there); it is kept under the study's name so the
-- next challenger reads the columns the study fitted. weekday: duckdb's dayofweek of as_of's UTC date, Sunday 0.
with s as (select case_id, crm_customer_id, as_of from {{ ref('feature_spine') }}),
out as (
    select case_id, contact_ts_utc, coalesce(rpc_flag, false) as rpc, coalesce(ptp_made_flag, false) as ptp_made
    from {{ ref('contact_history') }} where direction = 'outbound'
),
agg as (
    select s.case_id, s.as_of,
        count(*) filter (where o.contact_ts_utc > s.as_of - interval 7 day) as n_out_7d,
        count(*) as n_out_30d,
        count(*) filter (where o.rpc) as n_rpc_30d,
        epoch(any_value(s.as_of) - max(o.contact_ts_utc)) / 86400.0 as days_since_contact,
        arg_max(o.rpc, o.contact_ts_utc) as last_rpc,
        arg_max(o.ptp_made, o.contact_ts_utc) as last_ptp_made
    from s join out o on o.case_id = s.case_id and o.contact_ts_utc <= s.as_of
        and o.contact_ts_utc > s.as_of - interval 30 day
    group by s.case_id, s.as_of
),
pend as (  -- open at as_of: made by then and not resolved by then
    select s.case_id, s.as_of, min(p.ptp_due_date) - min(cast(s.as_of as date)) as ptp_due_in_days
    from s join {{ ref('promises_to_pay') }} p on p.crm_customer_id = s.crm_customer_id
        and p.ptp_created_ts <= s.as_of and (p.status_ts is null or p.status_ts > s.as_of)
    group by s.case_id, s.as_of
),
paid_prev as (  -- a payment in the previous 7 days: a contact flag, or a promise paid
    select s.case_id, s.as_of from s join {{ ref('contact_history') }} h on h.crm_customer_id = s.crm_customer_id
        and (h.payment_taken_flag or h.link_payment_flag or h.app_payment_after_contact_flag)
        and h.contact_ts_utc <= s.as_of and h.contact_ts_utc > s.as_of - interval 7 day
    union
    select s.case_id, s.as_of from s join {{ ref('promises_to_pay') }} p on p.crm_customer_id = s.crm_customer_id
        and p.ptp_status in ('kept', 'partially_kept')
        and cast(p.paid_date as timestamp) + interval 12 hour <= s.as_of
        and cast(p.paid_date as timestamp) + interval 12 hour > s.as_of - interval 7 day
)
select s.case_id, s.as_of,
    p.case_id is not null as pending_ptp,
    p.ptp_due_in_days,
    coalesce(a.n_out_7d, 0) as n_out_7d,
    coalesce(a.n_out_30d, 0) as n_out_30d,
    coalesce(a.n_rpc_30d, 0) as n_rpc_30d,
    a.days_since_contact,
    a.last_rpc,
    a.last_ptp_made,
    w.case_id is not null as paid_prev7,
    dayofweek(s.as_of) as weekday
from s
left join agg a using (case_id, as_of)
left join pend p using (case_id, as_of)
left join paid_prev w using (case_id, as_of)
