{# Input of kept.data.identity.exact.exact_link_pairs: one row per piece of key evidence. #}
{# source_key = the customer key of that system (README "Customer keys"), not the account key. #}
select 'crm' as source_system, crm_customer_id as source_key, null as crm_ref,
       null as payment_source_account, null as deposit_account_id,
       national_id_hash, duplicate_of_crm_id, null as core_banking_cif
from {{ ref('customers') }}

union all
select 'collections', coll_customer_ref, coll_customer_ref, null, null, null, null, null
from {{ ref('collections_cases') }}
where coll_customer_ref is not null
group by coll_customer_ref

union all
select 'card', src_customer_ref, null, autopay_source_account, null, null, null, null
from {{ ref('card_accounts') }}

union all
select 'loan', src_customer_ref, null, pad_source_account, null, null, null, null
from {{ ref('loan_accounts') }}

union all
select 'deposit', src_customer_ref, null, null, deposit_account_id, null, null, src_customer_ref
from {{ ref('deposit_accounts') }}

union all
select 'bureau', bank_subject_ref, null, null, null, null, null, bank_subject_ref
from {{ ref('external') }}
