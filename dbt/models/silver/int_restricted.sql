{# The 12 protected attributes per golden ID, for compliance (c360_restricted). Never joined into #}
{# features or Ask; the lineage CI test enforces it. #}
with crm as (
    select x.golden_customer_id, c.*,
           struct_pack(ts := c.effective_from_ts, id := c.crm_customer_id) as recency
    from {{ ref('customers') }} c
    join {{ source('identity', 'int_crosswalk') }} x
        on x.source_system = 'crm' and x.source_key = c.crm_customer_id and x.valid_to is null
),
crm_latest as (
    select
        golden_customer_id,
        arg_max(gender_code, recency) filter (where gender_code is not null) as gender_code,
        arg_max(marital_status, recency) filter (where marital_status is not null) as marital_status,
        arg_max(citizenship_status, recency) filter (where citizenship_status is not null) as citizenship_status,
        arg_max(household_size, recency) filter (where household_size is not null) as household_size,
        arg_max(dependants_count, recency) filter (where dependants_count is not null) as dependants_count,
        bool_or(newcomer_program_flag) as newcomer_program_flag,
        arg_max(newcomer_arrival_date, recency) filter (where newcomer_arrival_date is not null) as newcomer_arrival_date,
        bool_or(accessibility_needs_flag) as accessibility_needs_flag,
        arg_max(accessibility_type, recency) filter (where accessibility_type is not null) as accessibility_type,
        arg_max(vulnerability_type, recency) filter (where vulnerability_type is not null) as vulnerability_type
    from crm
    group by golden_customer_id
),
ccb as (
    select x.golden_customer_id, bool_or(d.ccb_deposit_flag) as ccb_deposit_flag
    from {{ ref('deposit_accounts') }} d
    join {{ source('identity', 'int_crosswalk') }} x
        on x.source_system = 'deposit' and x.source_key = d.src_customer_ref and x.valid_to is null
    group by x.golden_customer_id
),
accent as (
    select golden_customer_id, mode(customer_accent_region) as customer_accent_region
    from (
        select x.golden_customer_id, v.customer_accent_region
        from {{ ref('voice_samples') }} v
        join {{ ref('call_transcripts') }} t on t.transcript_id = v.transcript_id
        join {{ source('identity', 'int_crosswalk') }} x
            on x.source_system = 'crm' and x.source_key = t.crm_customer_id and x.valid_to is null
        where v.customer_accent_region is not null
    )
    group by golden_customer_id
)
select
    c.golden_customer_id,
    c.gender_code,
    c.marital_status,
    c.citizenship_status,
    c.household_size,
    c.dependants_count,
    c.newcomer_program_flag,
    c.newcomer_arrival_date,
    c.accessibility_needs_flag,
    c.accessibility_type,
    c.vulnerability_type,
    b.ccb_deposit_flag,
    a.customer_accent_region
from crm_latest c
left join ccb b using (golden_customer_id)
left join accent a using (golden_customer_id)
