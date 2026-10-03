{# [<col>_m01, ..., <col>_m12]: the twelve monthly columns of an account snapshot as a list. #}
{% macro month_columns(col) -%}
    [{% for i in range(1, 13) %}{{ col }}_m{{ '%02d' % i }}{{ ', ' if not loop.last }}{% endfor %}]
{%- endmacro %}
