{# hardship_status from the AGENT and ACCOUNT sources only, until Track C's text extractions and #}
{# the cash-flow rule join at G2 (kept.hardship.combine). Rules follow combine's docstring: any signal #}
{# makes it at least POSSIBLE; an agent-coded flag or an account hardship programme is CLEAR #}
{# (confirmed); customer-form and model flags stay POSSIBLE until a person confirms. #}
with observations as (
    select golden_customer_id,
           case hardship_source when 'agent_coded' then 'agent' else hardship_source end as source,
           case when hardship_source = 'agent_coded' then 'clear' else 'possible' end as signal
    from {{ ref('int_open_case') }}
    where hardship_flag and hardship_source in ('agent_coded', 'customer_form', 'model')

    union all
    select x.golden_customer_id, 'account_programme', 'clear'
    from (
        select 'card' as source_system, src_customer_ref as source_key, hardship_program_flag, hardship_end_date
        from {{ ref('card_accounts') }}
        union all
        select 'loan', src_customer_ref, hardship_program_flag, hardship_end_date from {{ ref('loan_accounts') }}
    ) a
    join {{ source('identity', 'int_crosswalk') }} x
        on x.source_system = a.source_system and x.source_key = a.source_key and x.valid_to is null
    where a.hardship_program_flag
      and (a.hardship_end_date is null or a.hardship_end_date >= date '{{ var("as_of_date", "2026-09-28") }}')

    union all
    select x.golden_customer_id, 'agent', 'possible'
    from {{ ref('contact_history') }} h
    join {{ source('identity', 'int_crosswalk') }} x
        on x.source_system = 'crm' and x.source_key = h.crm_customer_id and x.valid_to is null
    where h.hardship_mentioned_flag
      and h.contact_ts_utc >= date '{{ var("as_of_date", "2026-09-28") }}' - interval 30 day
)
select
    golden_customer_id,
    case when bool_or(signal = 'clear') then 'confirmed' else 'possible' end as hardship_status,
    -- the source that set the final status: a clear observation first, then agent, account_programme,
    -- customer_form, model
    arg_min(source, struct_pack(
        unconfirmed := signal <> 'clear',
        priority := case source when 'agent' then 1 when 'account_programme' then 2 when 'customer_form' then 3 else 4 end
    )) as hardship_source
from observations
group by golden_customer_id
