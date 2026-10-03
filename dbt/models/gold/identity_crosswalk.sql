-- Track A: replace with the crosswalk produced by kept.data.identity.
select
    cast(null as varchar)     as golden_customer_id,
    cast(null as varchar)     as source_system,
    cast(null as varchar)     as source_key,
    cast(null as double)      as match_score,
    cast(null as varchar)     as match_rule,
    cast(null as varchar)     as match_review_status,
    cast(null as timestamptz) as linked_at,
    cast(null as timestamptz) as valid_to
where false
