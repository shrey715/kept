{{ config(enabled=var('training_spine', false)) }}
-- Uplift training rows, version 2 (training only): one row per case and weekly landmark, on a randomly assigned case.
--   decision_at: the landmark, 1, 8, ..., 120 days after the case opened, midnight; features are taken a second before.
--   action:      the first outbound contact (call / sms_payment_link / email / push) in the 2 days from the landmark, or wait when
--                there was no outbound contact of any kind in those 2 days. Landmarks whose first contact is unmapped (letters) are left out.
--   label_at:    the 14-day outcome windows start 2 days after the landmark (decision_at + 2 days), after the contact window closes, and
--                a case has to be open then. Counting outcomes from the landmark itself would give WAIT the cases that closed (cured) in
--                the first days of the week, since a closed case is no longer contacted: a "wait" that is really an early cure.
-- One row per case-landmark instead of one per attempt: five calls in a day are one decision, and WAIT comes from the same landmarks.
{% set start = var("training_start", "2025-09-01") %}
{% set snapshot = var("training_snapshot", "2026-09-28") %}
with cases as (
    select case_id, coll_customer_ref as crm_customer_id, primary_product, entry_dpd, case_open_date, outcome_date
    from {{ ref('collections_cases') }}
    where assignment_method = 'random'
),
weeks as (
    select 'WK-' || c.case_id || '-' || n as decision_id, c.case_id, c.crm_customer_id,
           cast(c.case_open_date as timestamp) + to_days(cast(n as integer)) as decision_at
    from cases c
    cross join (select unnest(range(1, 121, 7)) as n) days
    where (c.outcome_date is null or c.outcome_date > c.case_open_date + cast(n as integer) + 2)
),
decisions0 as (
    select * from weeks
    where decision_at >= cast('{{ start }}' as timestamp)
      and decision_at + interval 16 day <= cast('{{ snapshot }}' as timestamp)
),
outbound as (
    select h.case_id, h.contact_ts_utc,
        case lower(h.treatment_code) || '|' || lower(h.channel)
            when 'outbound_call|call' then 'call'
            when 'payment_link|sms' then 'sms_payment_link'
            when 'email_reminder|email' then 'email'
            when 'push|push' then 'push'
        end as action
    from {{ ref('contact_history') }} h
    where h.direction = 'outbound' and h.case_id in (select case_id from cases)
),
first_contact as (
    select d.decision_id, count(*) as n_contacts_2d,
           arg_min(o.action, o.contact_ts_utc) as first_action,
           count(*) filter (where o.action is null) as n_unmapped
    from decisions0 d join outbound o on o.case_id = d.case_id
        and o.contact_ts_utc >= d.decision_at and o.contact_ts_utc < d.decision_at + interval 2 day
    group by d.decision_id
),
decisions as (
    select d.decision_id, d.case_id, d.crm_customer_id, d.decision_at, d.decision_at + interval 2 day as label_at,
           coalesce(f.first_action, 'wait') as action, coalesce(f.n_contacts_2d, 0) as n_contacts_2d
    from decisions0 d left join first_contact f using (decision_id)
    where f.decision_id is null or f.first_action is not null
),
{{ payment_events() }},
{{ payment_labels() }}
select l.*, l.paid_14d or l.covered as paid_14d_known
from labelled l
