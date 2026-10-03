-- One row per (case, as_of) for every case open at as_of. Times are naive UTC (pre-hook sets TimeZone).
-- Training: set vars features_start < features_as_of for a weekly history spine.
with as_of as (
    select unnest(generate_series(
        cast('{{ var("features_start", var("features_as_of")) }}' as timestamp),
        cast('{{ var("features_as_of") }}' as timestamp),
        interval '{{ var("features_step_days") }} days'
    )) as as_of
)
select
    c.case_id,
    c.coll_customer_ref as crm_customer_id,
    c.primary_product,
    {{ dpd_bucket('c.entry_dpd') }} as entry_bucket,
    a.as_of
from {{ source('silver', 'collections_cases') }} c
join as_of a
    on c.case_open_date <= cast(a.as_of as date)
    and (c.outcome_date is null or c.outcome_date > cast(a.as_of as date))
