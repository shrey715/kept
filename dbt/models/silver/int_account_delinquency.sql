{# Across the current account snapshots (silver keeps the latest row per account). #}
{# Card dpd, never cycles_delinquent; deposits contribute overdraft_dpd. #}
with accounts as (
    select 'card' as source_system, src_customer_ref as source_key, past_due_amount as overdue, dpd
    from {{ ref('card_accounts') }}
    union all
    select 'loan', src_customer_ref, past_due_amount, dpd from {{ ref('loan_accounts') }}
    union all
    select 'deposit', src_customer_ref, null, overdraft_dpd from {{ ref('deposit_accounts') }}
)
select
    x.golden_customer_id,
    coalesce(sum(greatest(coalesce(a.overdue, 0), 0)), 0)::decimal(18, 2) as total_overdue,
    coalesce(max(greatest(a.dpd, 0)), 0) as max_dpd,
    string_agg(distinct a.source_system, ', ') filter (where a.overdue > 0 or a.dpd > 0) as total_overdue_source
from accounts a
join {{ source('identity', 'int_crosswalk') }} x
    on x.source_system = a.source_system and x.source_key = a.source_key and x.valid_to is null
group by x.golden_customer_id
