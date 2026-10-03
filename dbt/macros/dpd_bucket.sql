{# Same edges as kept.contracts.enums.DpdBucket. #}
{% macro dpd_bucket(dpd) -%}
    case
        when {{ dpd }} is null then null
        when {{ dpd }} <= 0 then 'current'
        when {{ dpd }} <= 30 then '1-30'
        when {{ dpd }} <= 60 then '31-60'
        when {{ dpd }} <= 90 then '61-90'
        when {{ dpd }} <= 120 then '91-120'
        else '121+'
    end
{%- endmacro %}
