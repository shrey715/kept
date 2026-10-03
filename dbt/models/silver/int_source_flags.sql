{# Per golden ID: which contact stops fired on ANY linked source record. #}
with flag_map(flag, stop, is_do_not_contact, is_collections_hold) as (
    values
        ('internal_do_not_call_flag', null, true, false),
        ('cease_communication_flag', 'cease', true, false),
        ('cease_contact_flag', 'cease', true, false),
        ('cease_request_flag', 'cease', true, false),
        ('consumer_proposal_flag', 'insolvency', false, true),
        ('insolvency_hold_flag', 'insolvency', false, true),
        ('consumer_proposal_on_file_flag', 'insolvency', false, true),
        ('bankruptcy_flag', 'bankruptcy', false, true),
        ('bankruptcy_on_file_flag', 'bankruptcy', false, true),
        ('deceased_flag', 'deceased', false, true),
        ('deceased_hold_flag', 'deceased', false, true),
        ('deceased_indicator', 'deceased', false, true)
)
select
    x.golden_customer_id,
    bool_or(m.is_do_not_contact) as any_do_not_contact,
    bool_or(m.is_collections_hold) as any_collections_hold,
    list_sort(list_distinct(list(m.stop) filter (where m.stop is not null))) as hard_stops,
    string_agg(distinct e.source_system || '.' || e.flag, ', ') filter (where m.is_do_not_contact) as do_not_contact_sources,
    string_agg(distinct e.source_system || '.' || e.flag, ', ') filter (where m.is_collections_hold) as collections_hold_sources
from {{ ref('int_flag_events') }} e
join flag_map m using (flag)
join {{ source('identity', 'int_crosswalk') }} x
    on x.source_system = e.source_system and x.source_key = e.source_key and x.valid_to is null
group by x.golden_customer_id
