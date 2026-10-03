{# Every hardship signal about a golden ID, one row each: the input of kept.hardship.combine (run in SQL #}
{# by kept_combine_hardship, which tests/data/test_hardship_sql.py checks against the Python rules). #}
{# Sources: the open case's flags, account hardship programmes, hardship mentioned to an agent in the #}
{# last 30 days, Track C's text extractions of the open case's notes, and C's cash-flow rule #}
{# (hardship.cashflow_observations, Track C's PR #25: merge it before this one). #}
select golden_customer_id,
       case hardship_source when 'agent_coded' then 'agent' else hardship_source end as source,
       case when hardship_source = 'agent_coded' then 'clear' else 'possible' end as signal,
       observed_at,
       null::varchar as confirmed_by,
       null::varchar as cleared_by
from {{ ref('int_open_case') }}
where hardship_flag and hardship_source in ('agent_coded', 'customer_form', 'model')

union all
select x.golden_customer_id, 'account_programme', 'clear',
       cast(coalesce(a.hardship_start_date, date '{{ var("as_of_date", "2026-09-28") }}') as timestamp),
       null::varchar, null::varchar
from (
    select 'card' as source_system, src_customer_ref as source_key, hardship_program_flag,
           hardship_start_date, hardship_end_date
    from {{ ref('card_accounts') }}
    union all
    select 'loan', src_customer_ref, hardship_program_flag, hardship_start_date, hardship_end_date
    from {{ ref('loan_accounts') }}
) a
join {{ source('identity', 'int_crosswalk') }} x
    on x.source_system = a.source_system and x.source_key = a.source_key and x.valid_to is null
where a.hardship_program_flag
  and (a.hardship_end_date is null or a.hardship_end_date >= date '{{ var("as_of_date", "2026-09-28") }}')

union all
select x.golden_customer_id, 'agent', 'possible', cast(h.contact_ts_utc as timestamp), null::varchar, null::varchar
from {{ ref('contact_history') }} h
join {{ source('identity', 'int_crosswalk') }} x
    on x.source_system = 'crm' and x.source_key = h.crm_customer_id and x.valid_to is null
where h.hardship_mentioned_flag
  and h.contact_ts_utc >= date '{{ var("as_of_date", "2026-09-28") }}' - interval 30 day

union all
-- text.extractions: a note on the open case. A person's confirmation (confirmed_by_agent_id) confirms it.
select oc.golden_customer_id, 'llm', e.hardship_signal_value, timezone('UTC', e.extracted_at),
       e.confirmed_by_agent_id, null::varchar
from {{ text_extractions() }} e
join {{ ref('int_open_case') }} oc on oc.open_case_id = e.case_id
where e.hardship_signal_value is not null

union all
-- cash flow (Track C): a late or lower payroll, or new EI deposits. Always 'possible': it only protects.
select golden_customer_id, source, signal, observed_at, confirmed_by, cleared_by
from {{ ref('cashflow_observations') }}
