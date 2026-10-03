{# One row per TRUE source flag: (source_system, source_key, flag). Mirrors kept.data.gold: #}
{# DO_NOT_CONTACT_FLAGS and HARD_STOP_FLAGS (tests/data/test_gold_sql.py keeps them in step). #}
{% macro flag_events(model, system, key_col, flags) -%}
{% for f in flags %}
select '{{ system }}' as source_system, {{ key_col }}::varchar as source_key, '{{ f }}' as flag
from {{ model }} where {{ f }}
{% if not loop.last %}union all{% endif %}
{% endfor %}
{%- endmacro %}
