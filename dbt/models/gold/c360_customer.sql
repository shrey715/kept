-- One row per golden ID. The logic lives in silver.int_* (K8: this final select is the contract).
-- hardship_status: agent and account sources only until G2 (silver.int_hardship).
select
    g.golden_customer_id as golden_customer_id,
    g.source_keys as source_keys,
    g.match_confidence_min as match_confidence_min,
    g.match_review_status as match_review_status,
    crm.display_name as display_name,
    crm.primary_phone_e164 as primary_phone_e164,
    crm.email as email,
    crm.province_code as province_code,
    crm.time_zone as time_zone,
    crm.preferred_language as preferred_language,
    coalesce(d.total_overdue, 0)::decimal(18, 2) as total_overdue,
    coalesce(d.max_dpd, 0)::integer as max_dpd,
    {{ dpd_bucket('coalesce(d.max_dpd, 0)') }} as current_bucket,
    oc.open_case_id as open_case_id,
    oc.assigned_agent_id as assigned_agent_id,
    coalesce(crm.contact_permissions, {'call': false, 'sms': false, 'email': false, 'push': false}) as contact_permissions,
    crm.permitted_call_start_local as permitted_call_start_local,
    crm.permitted_call_end_local as permitted_call_end_local,
    coalesce(crm.sunday_contact_permitted, false) as sunday_contact_permitted,
    coalesce(f.any_do_not_contact, false) as do_not_contact,
    coalesce(f.any_collections_hold, false) as collections_hold,
    coalesce(f.hard_stops, []::varchar[]) as hard_stop_flags,
    coalesce(h.hardship_status, 'none') as hardship_status,
    h.hardship_source as hardship_source,
    coalesce(crm.vulnerability_flag, false) or coalesce(oc.vulnerable_customer_flag, false) as vulnerability_flag,
    p.expected_next_payroll_date as expected_next_payroll_date,
    coalesce(p.payroll_frequency_detected, 'unknown') as payroll_frequency_detected,
    cast('{{ var("as_of_date", "2026-09-28") }}' as date) as as_of_date,
    cast(current_timestamp as timestamptz) as refreshed_at,
    crm.display_name_source as display_name_source,
    crm.primary_phone_e164_source as primary_phone_e164_source,
    crm.email_source as email_source,
    crm.province_code_source as province_code_source,
    crm.time_zone_source as time_zone_source,
    crm.preferred_language_source as preferred_language_source,
    d.total_overdue_source as total_overdue_source,
    crm.contact_permissions_source as contact_permissions_source,
    f.do_not_contact_sources as do_not_contact_source,
    f.collections_hold_sources as collections_hold_source,
    p.expected_next_payroll_date_source as expected_next_payroll_date_source
from {{ ref('int_golden_clusters') }} g
left join {{ ref('int_crm_current') }} crm using (golden_customer_id)
left join {{ ref('int_account_delinquency') }} d using (golden_customer_id)
left join {{ ref('int_open_case') }} oc using (golden_customer_id)
left join {{ ref('int_source_flags') }} f using (golden_customer_id)
left join {{ ref('int_hardship') }} h using (golden_customer_id)
left join {{ ref('int_payroll') }} p using (golden_customer_id)
