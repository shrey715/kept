-- kept.features.definitions.contacts_last_7d / answer_rate, point in time.
-- Attempts are our outbound contacts: inbound calls and internal system events don't use the cap.
with attempts as (
    select * from {{ ref('contact_history') }}
    where direction = 'outbound'
),
per_customer as (
    select
        s.case_id,
        s.as_of,
        avg(case when h.dial_result = 'answered' then 1.0 else 0.0 end)
            filter (where h.channel = 'call') as answer_rate,
        avg(case when h.dial_result = 'answered' then 1.0 else 0.0 end)
            filter (where h.channel = 'call' and h.contact_hour_local >= 18) as answer_rate_after_18h,
        avg(case when h.link_payment_flag then 1.0 else 0.0 end)
            filter (where h.payment_link_id is not null) as payment_link_usage
    from {{ ref('feature_spine') }} s
    left join attempts h
        on h.crm_customer_id = s.crm_customer_id
        and h.contact_ts_utc <= s.as_of
    group by all
),
per_case as (
    select s.case_id, s.as_of, count(h.case_id) as contacts_last_7d
    from {{ ref('feature_spine') }} s
    left join attempts h
        on h.case_id = s.case_id
        and h.contact_ts_utc > s.as_of - interval 7 day
        and h.contact_ts_utc <= s.as_of
    group by all
)
select * from per_customer join per_case using (case_id, as_of)
