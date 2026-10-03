-- kept.features.definitions.cohort_rate over OTHER cases closed before as_of, grouped by
-- product x entry bucket (known at case open, so point in time). Groups under 50 -> null.
with keys as (
    select distinct as_of, primary_product, entry_bucket from {{ ref('feature_spine') }}
),
closed as (
    select primary_product, {{ dpd_bucket('entry_dpd') }} as entry_bucket, outcome_date, cure_flag, case_id
    from {{ source('silver', 'collections_cases') }}
    where outcome_date is not null
),
recovery as (
    select k.as_of, k.primary_product, k.entry_bucket,
           count(c.case_id) as n, count(c.case_id) filter (where c.cure_flag) as cured
    from keys k
    left join closed c
        on c.primary_product = k.primary_product
        and c.entry_bucket = k.entry_bucket
        and c.outcome_date < cast(k.as_of as date)
    group by all
),
promises as (
    select k.as_of, k.primary_product, k.entry_bucket,
           count(p.ptp_id) as n, count(p.ptp_id) filter (where p.ptp_status = 'kept') as kept
    from keys k
    left join (
        select p.ptp_id, p.ptp_status, p.status_ts, c.primary_product, {{ dpd_bucket('c.entry_dpd') }} as entry_bucket
        from {{ source('silver', 'promises_to_pay') }} p
        join {{ source('silver', 'collections_cases') }} c using (case_id)
        where p.ptp_status in ('kept', 'partially_kept', 'broken')
    ) p
        on p.primary_product = k.primary_product
        and p.entry_bucket = k.entry_bucket
        and p.status_ts <= k.as_of
    group by all
)
select
    s.case_id,
    s.as_of,
    case when r.n >= 50 then cast(r.cured as double) / r.n end as cohort_recovery_rate,
    case when p.n >= 50 then cast(p.kept as double) / p.n end as cohort_kept_rate
from {{ ref('feature_spine') }} s
join recovery r using (as_of, primary_product, entry_bucket)
join promises p using (as_of, primary_product, entry_bucket)
