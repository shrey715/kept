-- One row per (source_system, source_key) link, from the match step (kept match -> kept build loads it).
select
    golden_customer_id as golden_customer_id,
    source_system as source_system,
    source_key as source_key,
    cast(match_score as double) as match_score,
    match_rule as match_rule,
    match_review_status as match_review_status,
    cast(linked_at as timestamptz) as linked_at,
    cast(valid_to as timestamptz) as valid_to
from {{ source('identity', 'int_crosswalk') }}
