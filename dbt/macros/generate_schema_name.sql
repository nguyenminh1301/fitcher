{# Use a model's configured schema (a ClickHouse database) verbatim instead of
   dbt's default "<target>_<custom>" naming, so models land in raw or marts. #}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
