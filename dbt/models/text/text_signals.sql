-- Text features per note / call (Track C), for D's features and A's gold hardship_status (G2).
-- One row per source_id with its time, so readers join point in time (written_at <= as_of).
-- cease_request_flag is true only once an agent confirmed it: text cease failed the F1 gate on
-- precision (holdout 0.50 notes / 0.20 transcripts), so an unconfirmed one never sets a hard stop.
-- It stays visible as cease_request_suggested for the card's "possible cease: confirm" prompt.
-- SetFit backfill rows (extractor 'setfit:%') only predict hardship: every other field is NULL
-- ("unknown"), not false, so history doesn't teach the uplift model "no promise was ever said"
-- while live LLM notes can say yes (promise_intent is a model input).
select
    x.source_id,
    x.case_id,
    case when n.note_id is not null then 'note' else 'transcript' end as source_type,
    coalesce(n.note_ts_utc, try_cast(t.call_start_ts as timestamp), x.extracted_at) as written_at,  -- calls: local; typed notes: extraction time
    x.hardship_signal_value                                             as hardship_signal,
    case when x.extractor not like 'setfit:%' then x.stated_reason_value end as stated_reason,
    case when x.extractor not like 'setfit:%' then x.promise_intent_value end as promise_intent,
    case when x.extractor not like 'setfit:%' then x.promised_date_value end as promised_date,
    case when x.extractor not like 'setfit:%' then x.promised_amount_value end as promised_amount,
    case when x.extractor not like 'setfit:%' then x.dispute_value end as dispute_flag,
    case when x.extractor not like 'setfit:%' then x.cease_request_value and x.confirmed_by_agent_id is not null end as cease_request_flag,
    case when x.extractor not like 'setfit:%' then x.cease_request_value and x.confirmed_by_agent_id is null end as cease_request_suggested,
    case when x.extractor not like 'setfit:%' then x.third_party_present_value end as third_party_present_flag,
    x.extractor,
    x.extracted_at,
    x.confirmed_by_agent_id
from {{ source('text', 'extractions') }} x
left join {{ ref('agent_notes') }} n on n.note_id = x.source_id
left join {{ ref('call_transcripts') }} t on t.transcript_id = x.source_id
