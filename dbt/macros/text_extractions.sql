{# text.extractions is written by Track C's extraction run; until it exists gold still builds, with no #}
{# text observations (so hardship_status is agent and account only, as before G2). #}
{% macro text_extractions() -%}
    {%- set rel = adapter.get_relation(database=target.database, schema='text', identifier='extractions') -%}
    {%- if rel is not none -%}
        {{ rel }}
    {%- else -%}
        (select null::varchar as case_id, null::varchar as hardship_signal_value,
                null::timestamptz as extracted_at, null::varchar as confirmed_by_agent_id where false)
    {%- endif -%}
{%- endmacro %}
