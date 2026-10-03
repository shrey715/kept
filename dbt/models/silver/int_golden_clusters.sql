{# One row per golden ID from the active crosswalk links. #}
select
    golden_customer_id,
    list_sort(list(source_system || ':' || source_key)) as source_keys,
    case when count(*) > 1 then min(coalesce(match_score, 1.0)) end as match_confidence_min,
    case
        when bool_or(match_review_status = 'steward_approved') then 'steward_approved'
        when count(*) > 1 then 'auto'
        else 'unlinked'
    end as match_review_status
from {{ source('identity', 'int_crosswalk') }}
where valid_to is null
group by golden_customer_id
