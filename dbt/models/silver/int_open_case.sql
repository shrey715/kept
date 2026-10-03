{# The open collections case of each golden ID (outcome is null); the latest opened if there are two. #}
select
    x.golden_customer_id,
    c.case_id as open_case_id,
    c.assigned_agent_id,
    c.hardship_flag,
    c.hardship_source,
    cast(coalesce(c.case_status_date, c.case_open_date) as timestamp) as observed_at,
    coalesce(c.vulnerable_customer_flag, false) as vulnerable_customer_flag
from {{ ref('collections_cases') }} c
join {{ source('identity', 'int_crosswalk') }} x
    on x.source_system = 'collections' and x.source_key = c.coll_customer_ref and x.valid_to is null
where c.outcome is null
qualify row_number() over (
    partition by x.golden_customer_id order by c.case_open_date desc, c.case_id desc
) = 1
