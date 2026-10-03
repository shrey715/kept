{# How each name token is used in CRM, where first_name and last_name are separate columns: #}
{# last_share near 1 = a surname, near 0 = a given name. Used to read loans' "First Last" / "Last First". #}
with tokens as (
    select regexp_replace(lower(strip_accents(first_name)), '[^a-z]', '', 'g') as token, 1 as is_first, 0 as is_last
    from {{ ref('customers') }}
    union all
    select regexp_replace(lower(strip_accents(last_name)), '[^a-z]', '', 'g'), 0, 1
    from {{ ref('customers') }}
)
select token, (sum(is_last) + 0.5) / (sum(is_first) + sum(is_last) + 1) as last_share
from tokens
where token <> ''
group by token
