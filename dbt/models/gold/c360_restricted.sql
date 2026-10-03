-- Track A: the 12 protected attributes (data dictionary), compliance only.
-- Sources: customers (10), deposit_accounts.ccb_deposit_flag, voice_samples.customer_accent_region.
-- Never ref() this from features or ask models; the lineage CI test enforces it.
select
    cast(null as varchar) as golden_customer_id,
    cast(null as varchar) as gender_code,
    cast(null as varchar) as marital_status,
    cast(null as varchar) as citizenship_status,
    cast(null as integer) as household_size,
    cast(null as integer) as dependants_count,
    cast(null as boolean) as newcomer_program_flag,
    cast(null as date) as newcomer_arrival_date,
    cast(null as boolean) as accessibility_needs_flag,
    cast(null as varchar) as accessibility_type,
    cast(null as varchar) as vulnerability_type,
    cast(null as boolean) as ccb_deposit_flag,
    cast(null as varchar) as customer_accent_region
where false
