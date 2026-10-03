{# Input of kept.data.identity.probabilistic.score_pairs: one row per (system, customer key) with the #}
{# cleaned match columns. name_key = "<surname> <first initial>" (kept.data.clean.match_name). #}
{# One customer key can own several accounts: min() keeps the pick deterministic. #}
select 'crm' as source_system, crm_customer_id as source_key,
       kept_match_name_parts(first_name, last_name) as name_key,
       dob_clean::varchar as dob, primary_phone_clean as phone_e164, postal_code_clean as postal_code,
       national_id_hash
from {{ ref('customers') }}

union all
select 'card', src_customer_ref,
       min(kept_match_name_card(cardholder_name_raw)), min(cardholder_dob_clean)::varchar,
       min(cardholder_phone_e164), min(cardholder_postal_clean), null
from {{ ref('card_accounts') }}
group by src_customer_ref

union all
select 'loan', src_customer_ref,
       min(kept_match_name_first_last(borrower_name_raw)), min(borrower_dob_clean)::varchar,
       min(borrower_phone_e164), min(borrower_postal_clean), null
from {{ ref('loan_accounts') }}
group by src_customer_ref

union all
select 'deposit', src_customer_ref,
       min(kept_match_name_last_initials(holder_name_raw)), min(holder_dob_clean)::varchar,
       min(holder_phone_e164), min(holder_postal_clean), null
from {{ ref('deposit_accounts') }}
group by src_customer_ref

union all
select 'bureau', bank_subject_ref,
       min(kept_match_name_last_comma(subject_name_reported)), min(subject_dob_reported)::varchar,
       null,
       min(kept_postal(regexp_extract(subject_address_reported, '[A-Za-z][0-9][A-Za-z] ?[0-9][A-Za-z][0-9]'))),
       null
from {{ ref('external') }}
group by bank_subject_ref
