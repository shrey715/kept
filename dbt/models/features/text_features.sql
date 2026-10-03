-- Text features per (case, as_of) from C's per-note text_signals, point in time (written_at <= as_of).
--   hardship_signal: strongest signal in the 90 days before as_of (hardship persists; a later "none"
--                    note doesn't erase a "possible")
--   promise_*:       the latest note with a promise, in the 30 days before as_of
--   dispute_flag:    any dispute in the 90 days before as_of
--   cease_request_flag: any agent-confirmed cease, ever (text_signals sets it only once confirmed)
--   third_party_present_flag: the latest note's value
with notes as (
    select s.case_id, s.as_of, t.*
    from {{ ref('feature_spine') }} s
    join {{ ref('text_signals') }} t on t.case_id = s.case_id and t.written_at <= s.as_of
),
latest as (
    select case_id, as_of, third_party_present_flag
    from notes
    qualify row_number() over (partition by case_id, as_of order by written_at desc, source_id desc) = 1
),
promise as (
    select case_id, as_of, promise_intent, promised_date, promised_amount
    from notes
    where promise_intent and written_at > as_of - interval 30 day
    qualify row_number() over (partition by case_id, as_of order by written_at desc, source_id desc) = 1
),
agg as (
    select
        case_id,
        as_of,
        max(case hardship_signal when 'clear' then 2 when 'possible' then 1 else 0 end)
            filter (where written_at > as_of - interval 90 day) as hardship_rank,
        coalesce(bool_or(dispute_flag) filter (where written_at > as_of - interval 90 day), false) as dispute_flag,
        coalesce(bool_or(cease_request_flag), false) as cease_request_flag
    from notes
    group by all
)
select
    a.case_id,
    a.as_of,
    case a.hardship_rank when 2 then 'clear' when 1 then 'possible' when 0 then 'none' end as hardship_signal,
    p.promise_intent,
    p.promised_date,
    p.promised_amount,
    a.dispute_flag,
    a.cease_request_flag,
    l.third_party_present_flag
from agg a
left join promise p using (case_id, as_of)
left join latest l using (case_id, as_of)
