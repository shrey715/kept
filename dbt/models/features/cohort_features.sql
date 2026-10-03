-- kept.features.definitions.cohort_rate over OTHER cases closed before as_of, grouped by
-- product x entry bucket (known at case open, so point in time). Groups under 50 -> null.
-- Running totals + ASOF join, so a training spine with one as_of per decision stays linear.
with keys as (
    select distinct as_of, cast(as_of as date) - 1 as closed_by, primary_product, entry_bucket
    from {{ ref('feature_spine') }}
),
recovery as (  -- cumulative closed / cured per group, by outcome date
    select primary_product, entry_bucket, outcome_date,
           sum(count(*)) over w as n, sum(count(*) filter (where cure_flag)) over w as cured
    from (
        select primary_product, {{ dpd_bucket('entry_dpd') }} as entry_bucket, outcome_date, cure_flag
        from {{ ref('collections_cases') }}
        where outcome_date is not null
    )
    group by primary_product, entry_bucket, outcome_date
    window w as (partition by primary_product, entry_bucket order by outcome_date)
),
promises as (  -- cumulative resolved / kept promises per group, by status time
    select primary_product, entry_bucket, status_ts,
           sum(count(*)) over w as n, sum(count(*) filter (where ptp_status = 'kept')) over w as kept
    from (
        select p.ptp_status, p.status_ts, c.primary_product, {{ dpd_bucket('c.entry_dpd') }} as entry_bucket
        from {{ ref('promises_to_pay') }} p
        join {{ ref('collections_cases') }} c using (case_id)
        where p.ptp_status in ('kept', 'partially_kept', 'broken')
    )
    group by primary_product, entry_bucket, status_ts
    window w as (partition by primary_product, entry_bucket order by status_ts)
),
rates as (
    select k.as_of, k.primary_product, k.entry_bucket,
           case when r.n >= 50 then cast(r.cured as double) / r.n end as cohort_recovery_rate,
           case when p.n >= 50 then cast(p.kept as double) / p.n end as cohort_kept_rate
    from keys k
    asof left join recovery r
        on r.primary_product = k.primary_product and r.entry_bucket = k.entry_bucket
        and k.closed_by >= r.outcome_date
    asof left join promises p
        on p.primary_product = k.primary_product and p.entry_bucket = k.entry_bucket
        and k.as_of >= p.status_ts
)
select s.case_id, s.as_of, r.cohort_recovery_rate, r.cohort_kept_rate
from {{ ref('feature_spine') }} s
join rates r using (as_of, primary_product, entry_bucket)
