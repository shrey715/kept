-- Uplift training rows (Track D): one row per treatment decision on a randomly assigned case, with
-- the action taken and the paid_14d label. Agreed with A (TEAM_PLAN §9, PR #13).
--   decisions: outbound contacts (action = kept.nba.legacy.treatment_to_action) and, for the random
--              no-contact hold-out, WAIT the day after case open
--   paid_14d:  any payment in [decision_at, decision_at + 14 days] from: contact payment flags (a
--              payment taken during/after the contact counts, hence the inclusive start), kept or
--              partially kept promises, loan instalments, card/loan payments in transactions (sample),
--              late card payments on statements
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
holdout as (
    select 'HOLD-' || case_id as decision_id, case_id,
           cast(case_open_date as timestamp) + interval 1 day as decision_at, 'wait' as action
    from cases
    where test_cell = 'no_contact_holdout'
),
decisions as (
    select d.*, c.crm_customer_id, c.primary_product, c.entry_dpd, c.accounts
    from (select * from contacts where action is not null union all select * from holdout) d
    join cases c using (case_id)
    where d.decision_at >= cast('{{ start }}' as timestamp)
      and d.decision_at + interval 14 day <= cast('{{ snapshot }}' as timestamp)
),
case_accounts as (
    select distinct case_id, unnest(accounts) as account_id from decisions
),
-- payment events, keyed by case (account-level sources) or by customer (contacts, promises)
events as (
    select a.case_id, null::varchar as crm_customer_id, cast(i.paid_date as timestamp) + interval 12 hour as paid_at
    from {{ ref('loan_instalments') }} i join case_accounts a on a.account_id = i.loan_id
    where i.paid_date is not null
    union all
    select a.case_id, null, t.txn_ts
    from {{ ref('transactions') }} t join case_accounts a on a.account_id = t.target_account_id
    where t.txn_type in ('card_payment', 'loan_payment') and coalesce(t.returned_flag, false) = false
    union all
    select a.case_id, null, cast(s.first_payment_after_due_date as timestamp) + interval 12 hour
    from {{ ref('card_statements') }} s join case_accounts a on a.account_id = s.card_account_id
    where s.first_payment_after_due_date is not null
    union all
    select null, h.crm_customer_id, h.contact_ts_utc
    from {{ ref('contact_history') }} h
    where h.payment_taken_flag or h.link_payment_flag or h.app_payment_after_contact_flag
    union all
    select null, p.crm_customer_id, cast(p.paid_date as timestamp) + interval 12 hour
    from {{ ref('promises_to_pay') }} p
    where p.ptp_status in ('kept', 'partially_kept') and p.paid_date is not null
),
covered as (  -- cases whose "no payment" we can trust
    select distinct a.case_id
    from case_accounts a
    where a.account_id like 'L-%'
       or a.account_id in (select distinct target_account_id from {{ ref('transactions') }} where target_account_id is not null)
),
labelled as (
    select
        d.decision_id,
        d.case_id,
        d.crm_customer_id,
        d.primary_product,
        d.entry_dpd,
        d.decision_at,
        d.action,
        -- two EXISTS, not one with an OR: each becomes its own join (one OR'd join took 8 minutes)
        exists (
            select 1 from events e
            where e.case_id = d.case_id
              and e.paid_at >= d.decision_at and e.paid_at <= d.decision_at + interval 14 day
        ) or exists (
            select 1 from events e
            where e.crm_customer_id = d.crm_customer_id
              and e.paid_at >= d.decision_at and e.paid_at <= d.decision_at + interval 14 day
        ) as paid_14d
    from decisions d
)
select l.*, l.paid_14d or l.case_id in (select case_id from covered) as paid_14d_known
from labelled l
