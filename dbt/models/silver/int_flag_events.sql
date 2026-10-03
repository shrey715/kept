{# national_dncl_flag is deliberately absent: the National DNCL covers telemarketing, not collections. #}
{{ flag_events(ref('customers'), 'crm', 'crm_customer_id',
    ['internal_do_not_call_flag', 'cease_communication_flag', 'deceased_flag', 'bankruptcy_flag', 'consumer_proposal_flag']) }}
union all
{{ flag_events(ref('collections_cases'), 'collections', 'coll_customer_ref',
    ['cease_contact_flag', 'insolvency_hold_flag', 'deceased_hold_flag']) }}
union all
{{ flag_events(ref('contact_history'), 'crm', 'crm_customer_id', ['cease_request_flag']) }}
union all
{{ flag_events(ref('external'), 'bureau', 'bank_subject_ref',
    ['bankruptcy_on_file_flag', 'consumer_proposal_on_file_flag', 'deceased_indicator']) }}
