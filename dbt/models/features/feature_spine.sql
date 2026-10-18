-- One row per (case, as_of) for every case open at as_of. Times are naive UTC (pre-hook sets TimeZone).
-- History: set vars features_start < features_as_of for a weekly spine. Uplift training: training_spine.
{% if var('training_spine', false) %}
-- Training: one as_of per uplift decision, a second before it, so the contact's own outcome never leaks.
with as_of as (
    select distinct case_id, decision_at - interval 1 second as as_of
    from (select case_id, decision_at from {{ ref('training_rows') }} union all select case_id, decision_at from {{ ref('training_weeks') }})
)
{% else %}
with as_of as (
    select unnest(generate_series(
        cast('{{ var("features_start", var("features_as_of")) }}' as timestamp),
        cast('{{ var("features_as_of") }}' as timestamp),
        interval '{{ var("features_step_days") }} days'
    )) as as_of
)
{% endif %}
select
    c.case_id,
    c.coll_customer_ref as crm_customer_id,
    c.primary_product,
    {{ dpd_bucket('c.entry_dpd') }} as entry_bucket,
    c.total_overdue,  -- the latest balance: balance_at_risk is for sizing and ranking, never a model input
    a.as_of
from {{ ref('collections_cases') }} c
{% if var('training_spine', false) %}
join as_of a using (case_id)
{% else %}
join as_of a
    on c.case_open_date <= cast(a.as_of as date)
    and (c.outcome_date is null or c.outcome_date > cast(a.as_of as date))
{% endif %}
