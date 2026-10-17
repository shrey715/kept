-- Uplift training rows (Track D): one row per treatment decision on a randomly assigned case, with
-- the action taken and the paid_14d label. Agreed with A (TEAM_PLAN §9, PR #13).
--   decisions: outbound contacts (action = kept.nba.legacy.treatment_to_action) and WAIT: weekly
--              check-in days with no outbound contact that day (see `waits`)
--   paid_14d:  any payment in [decision_at, decision_at + 14 days] from: contact payment flags (a
--              payment taken during/after the contact counts, hence the inclusive start), kept or
--              partially kept promises, loan instalments, card/loan payments in transactions (sample),
--              late card payments on statements
--   paid_clean_14d: the same window, account-sourced records only (instalments, transactions, statements, kept promises): no contact
--              payment flags, which only a contacted decision can carry. Trust it where `covered`. paid_amt_14d: its dollars.
--   paid_14d_known: a "no" is trusted only where coverage is complete (a loan account, or an account
--              in the transactions sample); other rows are labelled only when a payment shows up.
-- Window: decisions from var training_start to 14 days before the snapshot (labels fully observed).
{% set start = var("training_start", "2025-09-01") %}
{% set snapshot = var("training_snapshot", "2026-09-28") %}
with cases as (
    select
        case_id,
        coll_customer_ref as crm_customer_id,
        primary_product,
        entry_dpd,
        test_cell,
        case_open_date,
        -- a JSON list, or one bare account ID (18K cases)
        case when account_ids like '[%' then from_json(account_ids, '["VARCHAR"]') else [account_ids] end as accounts
    from {{ ref('collections_cases') }}
    where assignment_method = 'random'
),
contacts as (
    select
        h.contact_id as decision_id,
        h.case_id,
        h.contact_ts_utc as decision_at,
        case lower(h.treatment_code) || '|' || lower(h.channel)
            when 'outbound_call|call' then 'call'
            when 'payment_link|sms' then 'sms_payment_link'
            when 'email_reminder|email' then 'email'
            when 'push|push' then 'push'
        end as action
    from {{ ref('contact_history') }} h
    join cases c using (case_id)
    where h.direction = 'outbound'
),
waits as (  -- "wait today": a weekly check-in day (1, 8, ..., 120 days after open) with no outbound
    -- contact that day, on any randomly assigned case while it is open. Not only the
    -- no_contact_holdout cell: its contact is delayed, not withheld (median first contact day 12
    -- vs 6), and the WAIT arm must cover the same stretch of case life as the contacts.
    select 'WAIT-' || c.case_id || '-' || n as decision_id, c.case_id,
           cast(c.case_open_date as timestamp) + to_days(cast(n as integer)) as decision_at, 'wait' as action
    from cases c
    join {{ ref('collections_cases') }} cc using (case_id)
    cross join (select unnest(range(1, 121, 7)) as n) days
    where cc.outcome_date is null or cc.outcome_date > c.case_open_date + cast(n as integer)
),
quiet as (
    select w.*
    from waits w
    where not exists (
        select 1 from {{ ref('contact_history') }} h
        where h.case_id = w.case_id and h.direction = 'outbound'
          and h.contact_ts_utc >= w.decision_at and h.contact_ts_utc < w.decision_at + interval 1 day
    )
),
decisions as (
    select d.*, d.decision_at as label_at, c.crm_customer_id, c.primary_product, c.entry_dpd, c.accounts
    from (select * from contacts where action is not null union all select * from quiet) d
    join cases c using (case_id)
    where d.decision_at >= cast('{{ start }}' as timestamp)
      and d.decision_at + interval 14 day <= cast('{{ snapshot }}' as timestamp)
),
-- payment events, labels and `covered`: macros/payment_events.sql
{{ payment_events() }},
{{ payment_labels() }}
select l.*, l.paid_14d or l.covered as paid_14d_known
from labelled l
