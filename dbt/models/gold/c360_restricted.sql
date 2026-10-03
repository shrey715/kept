-- The 12 protected attributes (data dictionary), compliance only. Built in silver.int_restricted.
-- Never ref() this from features or ask models; the lineage CI test enforces it.
select
    golden_customer_id as golden_customer_id,
    gender_code as gender_code,
    marital_status as marital_status,
    citizenship_status as citizenship_status,
    cast(household_size as integer) as household_size,
    cast(dependants_count as integer) as dependants_count,
    newcomer_program_flag as newcomer_program_flag,
    newcomer_arrival_date as newcomer_arrival_date,
    accessibility_needs_flag as accessibility_needs_flag,
    accessibility_type as accessibility_type,
    vulnerability_type as vulnerability_type,
    ccb_deposit_flag as ccb_deposit_flag,
    customer_accent_region as customer_accent_region
from {{ ref('int_restricted') }}
