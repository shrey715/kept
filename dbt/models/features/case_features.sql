-- The feature table Feast serves: one row per (case_id, as_of), columns = feature_registry.FEATURES.
-- Null columns are filled later: account/deposit features need A's crosswalk and gold (G2),
-- text features need C's text.extractions (G0 shape, G2 data).
select
    s.case_id,
    x.golden_customer_id,
    s.as_of,
    '{{ var("feature_set_version") }}' as feature_set_version,
    cast(null as integer)                         as max_dpd,
    cast(null as integer)                         as times_30plus_dpd_12m,
    cast(null as integer)                         as days_in_bucket,
    cast(null as decimal(14, 2))                  as balance_at_risk,
    cast(p.broken_promises_90d as integer)        as broken_promises_90d,
    p.kept_promise_ratio                          as kept_promise_ratio,
    cast(null as integer)                         as days_to_next_payroll,
    cast(null as varchar)                         as pay_frequency,
    cast(null as integer)                         as payroll_delay_days,
    cast(null as double)                          as pay_change_vs_3m_avg,
    cast(null as decimal(14, 2))                  as estimated_monthly_spare_cash,
    cast(null as double)                          as cash_flow_trend,
    cast(null as double)                          as card_utilisation_trend,
    h.answer_rate                                 as answer_rate,
    h.answer_rate_after_18h                       as answer_rate_after_18h,
    h.payment_link_usage                          as payment_link_usage,
    cast(h.contacts_last_7d as integer)           as contacts_last_7d,
    k.cohort_recovery_rate                        as cohort_recovery_rate,
    k.cohort_kept_rate                            as cohort_kept_rate,
    cast(null as varchar)                         as hardship_signal,
    cast(null as boolean)                         as promise_intent,
    cast(null as date)                            as promised_date,
    cast(null as decimal(14, 2))                  as promised_amount,
    cast(null as boolean)                         as dispute_flag,
    cast(null as boolean)                         as cease_request_flag,
    cast(null as boolean)                         as third_party_present_flag
from {{ ref('feature_spine') }} s
left join {{ ref('promise_features') }} p using (case_id, as_of)
left join {{ ref('contact_features') }} h using (case_id, as_of)
left join {{ ref('cohort_features') }} k using (case_id, as_of)
left join {{ ref('identity_crosswalk') }} x
    on x.source_system = 'crm' and x.source_key = s.crm_customer_id and x.valid_to is null
