-- kept.features.definitions.broken_promises_90d / kept_promise_ratio, per customer, point in time.
select
    s.case_id,
    s.as_of,
    count(*) filter (
        where p.ptp_status = 'broken'
        and p.ptp_due_date > cast(s.as_of as date) - 90
        and p.ptp_due_date <= cast(s.as_of as date)
    ) as broken_promises_90d,
    cast(count(*) filter (where p.ptp_status = 'kept') as double)
        / nullif(count(*) filter (where p.ptp_status in ('kept', 'partially_kept', 'broken')), 0)
        as kept_promise_ratio
from {{ ref('feature_spine') }} s
left join {{ ref('promises_to_pay') }} p
    on p.crm_customer_id = s.crm_customer_id
    and p.status_ts <= s.as_of
group by all
