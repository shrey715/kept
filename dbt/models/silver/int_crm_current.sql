{# Per golden ID, the most recent CRM value (latest effective_from_ts, then key) of each field, with the #}
{# CRM record it came from; consent is the most restrictive across the cluster's CRM records. #}
with crm as (
    select x.golden_customer_id, c.*,
           struct_pack(ts := c.effective_from_ts, id := c.crm_customer_id) as recency
    from {{ ref('customers') }} c
    join {{ source('identity', 'int_crosswalk') }} x
        on x.source_system = 'crm' and x.source_key = c.crm_customer_id and x.valid_to is null
)
select
    golden_customer_id,
    arg_max(full_name_clean, recency) filter (where full_name_clean is not null) as display_name,
    arg_max('crm:' || crm_customer_id, recency) filter (where full_name_clean is not null) as display_name_source,
    arg_max(primary_phone_clean, recency) filter (where primary_phone_clean is not null) as primary_phone_e164,
    arg_max('crm:' || crm_customer_id, recency) filter (where primary_phone_clean is not null) as primary_phone_e164_source,
    arg_max(email, recency) filter (where email is not null) as email,
    arg_max('crm:' || crm_customer_id, recency) filter (where email is not null) as email_source,
    arg_max(province_code_clean, recency) filter (where province_code_clean is not null) as province_code,
    arg_max('crm:' || crm_customer_id, recency) filter (where province_code_clean is not null) as province_code_source,
    arg_max(time_zone, recency) filter (where time_zone is not null) as time_zone,
    arg_max('crm:' || crm_customer_id, recency) filter (where time_zone is not null) as time_zone_source,
    arg_max(preferred_language, recency) filter (where preferred_language is not null) as preferred_language,
    arg_max('crm:' || crm_customer_id, recency) filter (where preferred_language is not null) as preferred_language_source,
    -- unknown consent (null) blocks the channel, like kept.data.gold.merge_contact_permissions
    struct_pack(
        call := bool_and(coalesce(consent_call, false)),
        sms := bool_and(coalesce(consent_sms, false)),
        email := bool_and(coalesce(consent_email, false)),
        push := bool_and(coalesce(consent_push, false))
    ) as contact_permissions,
    string_agg('crm:' || crm_customer_id, ', ' order by crm_customer_id) as contact_permissions_source,
    max(try_cast(permitted_call_start_local as time)) as permitted_call_start_local,
    min(try_cast(permitted_call_end_local as time)) as permitted_call_end_local,
    bool_and(coalesce(sunday_contact_permitted, false)) as sunday_contact_permitted,
    bool_or(coalesce(vulnerability_flag, false)) as vulnerability_flag
from crm
group by golden_customer_id
