{# Input of kept.data.identity.probabilistic.score_pairs: one row per (system, customer key) with the #}
{# cleaned match columns. first_name_key is null where the system holds only an initial. name_key = "<surname> <first initial>" (kept.data.clean.match_name). #}
{# One customer key can own several accounts: min() keeps the pick deterministic. #}
select 'crm' as source_system, crm_customer_id as source_key,
       kept_match_name_parts(first_name, last_name) as name_key,
       kept_first_name(first_name) as first_name_key,
       dob_clean::varchar as dob, primary_phone_clean as phone_e164, postal_code_clean as postal_code,
       national_id_hash
from {{ ref('customers') }}

union all
select 'card', src_customer_ref,
       min(kept_match_name_card(cardholder_name_raw)), min(kept_first_name_card(cardholder_name_raw)),
       min(cardholder_dob_clean)::varchar,
       min(cardholder_phone_e164), min(cardholder_postal_clean), null
from {{ ref('card_accounts') }}
group by src_customer_ref

union all
{# loans write the name "First Last" or "Last First" (about 1 in 5): the token CRM uses more as a surname is the surname #}
select 'loan', src_customer_ref,
       surname || ' ' || left(given, 1) as name_key,
       case when length(given) > 1 then given end as first_name_key,
       dob, phone_e164, postal_code, null
from (
    select ln.src_customer_ref, ln.dob, ln.phone_e164, ln.postal_code,
           case when sa > sb then a else b end as surname,
           case when sa > sb then b else a end as given
    from (
        select src_customer_ref, a, b, dob, phone_e164, postal_code,
               coalesce(la.last_share, 0.5) as sa, coalesce(lb.last_share, 0.5) as sb
        from (
            select src_customer_ref,
                   regexp_replace(lower(strip_accents(split_part(min(borrower_name_raw), ' ', 1))), '[^a-z]', '', 'g') as a,
                   regexp_replace(lower(strip_accents(string_split(min(borrower_name_raw), ' ')[-1])), '[^a-z]', '', 'g') as b,
                   min(borrower_dob_clean)::varchar as dob, min(borrower_phone_e164) as phone_e164,
                   min(borrower_postal_clean) as postal_code
            from {{ ref('loan_accounts') }}
            where borrower_name_raw like '% %'
            group by src_customer_ref
        ) t
        left join {{ ref('int_name_lexicon') }} la on la.token = t.a
        left join {{ ref('int_name_lexicon') }} lb on lb.token = t.b
    ) ln
)
where surname <> '' and given <> ''

union all
select 'deposit', src_customer_ref,
       min(kept_match_name_last_initials(holder_name_raw)), null, min(holder_dob_clean)::varchar,
       min(holder_phone_e164), min(holder_postal_clean), null
from {{ ref('deposit_accounts') }}
group by src_customer_ref

union all
select 'bureau', bank_subject_ref,
       min(kept_match_name_last_comma(subject_name_reported)), min(kept_first_name_last_comma(subject_name_reported)),
       min(subject_dob_reported)::varchar,
       null,
       min(kept_postal(regexp_extract(subject_address_reported, '[A-Za-z][0-9][A-Za-z] ?[0-9][A-Za-z][0-9]'))),
       null
from {{ ref('external') }}
group by bank_subject_ref
