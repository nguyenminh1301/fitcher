{# Convert a float amount to Decimal(18, 2) through integer cents, so a value
   stored as 3.9899998 becomes exactly 3.99 instead of being truncated. #}
{% macro to_money(expr) -%}
    CAST(toInt64(round(toFloat64(assumeNotNull({{ expr }})) * 100)) AS Decimal(18, 2)) / 100
{%- endmacro %}
