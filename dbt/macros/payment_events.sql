{# CTEs `case_accounts` and `events` for the uplift labels (training_rows, training_weeks): every payment event of a randomly
   assigned case, keyed by case (account-level sources) or by customer (contacts, promises).
   src: loan | txn | stmt | ptp are account-sourced and do not depend on whether we contacted the customer; contact is a payment
   flag on a contact row (payment taken, link payment, app payment after contact), which only treated decisions can carry.
   amount: dollars where the source has them (stmt has none). #}
{% macro payment_events() %}
case_accounts as (
    select distinct case_id,
        unnest(case when account_ids like '[%' then from_json(account_ids, '["VARCHAR"]') else [account_ids] end) as account_id
    from {{ ref('collections_cases') }}
    where assignment_method = 'random'
),
events as (
    select a.case_id, null::varchar as crm_customer_id, cast(i.paid_date as timestamp) + interval 12 hour as paid_at,
           'loan' as src, cast(i.paid_amount as double) as amount
    from {{ ref('loan_instalments') }} i join case_accounts a on a.account_id = i.loan_id
    where i.paid_date is not null
    union all
    select a.case_id, null, t.txn_ts, 'txn', abs(cast(t.amount as double))
    from {{ ref('transactions') }} t join case_accounts a on a.account_id = t.target_account_id
    where t.txn_type in ('card_payment', 'loan_payment') and coalesce(t.returned_flag, false) = false
    union all
    select a.case_id, null, cast(s.first_payment_after_due_date as timestamp) + interval 12 hour, 'stmt', null
    from {{ ref('card_statements') }} s join case_accounts a on a.account_id = s.card_account_id
    where s.first_payment_after_due_date is not null
    union all
    select null, h.crm_customer_id, h.contact_ts_utc, 'contact', cast(h.payment_amount as double)
    from {{ ref('contact_history') }} h
    where h.payment_taken_flag or h.link_payment_flag or h.app_payment_after_contact_flag
    union all
    select null, p.crm_customer_id, cast(p.paid_date as timestamp) + interval 12 hour, 'ptp', cast(p.amount_paid_against as double)
    from {{ ref('promises_to_pay') }} p
    where p.ptp_status in ('kept', 'partially_kept') and p.paid_date is not null
),
covered as (  -- cases whose "no payment" we can trust: a loan account, or an account in the transactions sample
    select distinct a.case_id
    from case_accounts a
    where a.account_id like 'L-%'
       or a.account_id in (select distinct target_account_id from {{ ref('transactions') }} where target_account_id is not null)
)
{% endmacro %}

{# For `decisions` (decision_id, case_id, crm_customer_id, decision_at, label_at; the 14 days start at label_at): paid_14d (any source, as always), paid_clean_14d (no contact
   flags), paid_amt_14d (dollars from the account-level and promise sources: the largest of the three source totals, so a payment seen
   by two sources is not added twice), covered. Two joins, one per key: one OR'd join took 8 minutes. #}
{% macro payment_labels() %}
by_case as (
    select d.decision_id,
        count(*) as n_any, count(*) filter (where e.src != 'contact') as n_clean,
        sum(e.amount) filter (where e.src = 'loan') as a_loan, sum(e.amount) filter (where e.src = 'txn') as a_txn
    from decisions d join events e on e.case_id = d.case_id
        and e.paid_at >= d.label_at and e.paid_at <= d.label_at + interval 14 day
    group by d.decision_id
),
by_customer as (
    select d.decision_id,
        count(*) as n_any, count(*) filter (where e.src != 'contact') as n_clean,
        sum(e.amount) filter (where e.src = 'ptp') as a_ptp
    from decisions d join events e on e.crm_customer_id = d.crm_customer_id
        and e.paid_at >= d.label_at and e.paid_at <= d.label_at + interval 14 day
    group by d.decision_id
),
labelled as (
    select d.*,
        coalesce(bc.n_any, 0) + coalesce(bu.n_any, 0) > 0 as paid_14d,
        coalesce(bc.n_clean, 0) + coalesce(bu.n_clean, 0) > 0 as paid_clean_14d,
        greatest(coalesce(bc.a_loan, 0), coalesce(bc.a_txn, 0), coalesce(bu.a_ptp, 0)) as paid_amt_14d,
        d.case_id in (select case_id from covered) as covered
    from decisions d
    left join by_case bc using (decision_id)
    left join by_customer bu using (decision_id)
)
{% endmacro %}
