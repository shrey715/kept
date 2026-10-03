-- Text features per note / call (Track C), for D's features and A's gold hardship_status (G2).
-- One row per source_id with its time, so readers join point in time (written_at <= as_of).
-- cease_request_flag is true only once an agent confirmed it: text cease failed the F1 gate on
-- precision (holdout 0.50 notes / 0.20 transcripts), so an unconfirmed one never sets a hard stop.
-- It stays visible as cease_request_suggested for the card's "possible cease: confirm" prompt.
select
    x.source_id,
    x.case_id,
    case when n.note_id is not null then 'note' else 'transcript' end as source_type,
    coalesce(n.note_ts_utc, try_cast(t.call_start_ts as timestamp), x.extracted_at) as written_at,  -- calls: local; typed notes: extraction time
    x.hardship_signal_value                                             as hardship_signal,
    x.stated_reason_value                                               as stated_reason,
    x.promise_intent_value                                              as promise_intent,
    x.promised_date_value                                               as promised_date,
    x.promised_amount_value                                             as promised_amount,
    x.dispute_value                                                     as dispute_flag,
    x.cease_request_value and x.confirmed_by_agent_id is not null       as cease_request_flag,
    x.cease_request_value and x.confirmed_by_agent_id is null           as cease_request_suggested,
    x.third_party_present_value                                         as third_party_present_flag,
    x.extractor,
    x.extracted_at,
    x.confirmed_by_agent_id
from {{ source('text', 'extractions') }} x
left join {{ ref('agent_notes') }} n on n.note_id = x.source_id
left join {{ ref('call_transcripts') }} t on t.transcript_id = x.source_id
