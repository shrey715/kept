-- The feature table Feast serves: one row per (case_id, as_of), columns = feature_registry.FEATURES.
-- Account, payroll and cash-flow features: account_features.sql; text features: text_features.sql
-- (C's text_signals); the bank's context at as_of: context_features.sql.
select
    s.case_id,
    x.golden_customer_id,
    s.as_of,
    '{{ var("feature_set_version") }}' as feature_set_version,
    cast(a.max_dpd as integer)                    as max_dpd,
    cast(a.times_30plus_dpd_12m as integer)       as times_30plus_dpd_12m,
    cast(a.days_in_bucket as integer)             as days_in_bucket,
    cast(s.total_overdue as decimal(14, 2))       as balance_at_risk,
    cast(p.broken_promises_90d as integer)        as broken_promises_90d,
    p.kept_promise_ratio                          as kept_promise_ratio,
    cast(a.days_to_next_payroll as integer)       as days_to_next_payroll,
    a.pay_frequency                               as pay_frequency,
    cast(a.payroll_delay_days as integer)         as payroll_delay_days,
    a.pay_change_vs_3m_avg                        as pay_change_vs_3m_avg,
    cast(a.estimated_monthly_spare_cash as decimal(14, 2)) as estimated_monthly_spare_cash,
    a.cash_flow_trend                             as cash_flow_trend,
    a.card_utilisation_trend                      as card_utilisation_trend,
    h.answer_rate                                 as answer_rate,
    h.answer_rate_after_18h                       as answer_rate_after_18h,
    h.payment_link_usage                          as payment_link_usage,
    cast(h.contacts_last_7d as integer)           as contacts_last_7d,
    k.cohort_recovery_rate                        as cohort_recovery_rate,
    k.cohort_kept_rate                            as cohort_kept_rate,
    t.hardship_signal                             as hardship_signal,
    t.promise_intent                              as promise_intent,
    t.promised_date                               as promised_date,
    cast(t.promised_amount as decimal(14, 2))     as promised_amount,
    t.dispute_flag                                as dispute_flag,
    t.cease_request_flag                          as cease_request_flag,
    t.third_party_present_flag                    as third_party_present_flag,
    c.pending_ptp                                 as pending_ptp,
    cast(c.ptp_due_in_days as integer)            as ptp_due_in_days,
    cast(c.n_out_7d as integer)                   as n_out_7d,
    cast(c.n_out_30d as integer)                  as n_out_30d,
    cast(c.n_rpc_30d as integer)                  as n_rpc_30d,
    c.days_since_contact                          as days_since_contact,
    c.last_rpc                                    as last_rpc,
    c.last_ptp_made                               as last_ptp_made,
    c.paid_prev7                                  as paid_prev7,
    cast(c.weekday as integer)                    as weekday
from {{ ref('feature_spine') }} s
left join {{ ref('promise_features') }} p using (case_id, as_of)
left join {{ ref('contact_features') }} h using (case_id, as_of)
left join {{ ref('cohort_features') }} k using (case_id, as_of)
left join {{ ref('text_features') }} t using (case_id, as_of)
left join {{ ref('context_features') }} c using (case_id, as_of)
left join {{ ref('account_features') }} a using (case_id, as_of)
left join {{ ref('identity_crosswalk') }} x
    -- coll_customer_ref is a collections key (as in A's int_open_case); as a crm key it missed 3%
    on x.source_system = 'collections' and x.source_key = s.crm_customer_id and x.valid_to is null
