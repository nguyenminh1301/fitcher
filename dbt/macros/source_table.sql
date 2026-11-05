{# The relation of one table of a non-Hugging Face source: raw.<source>__<table>
   in copy mode or a table of src_<source> in live mode. jobs.refresh_data
   passes the map as the source_tables variable (jobs/lib/source_engines.py),
   so these models build over whichever source of their dbt tag was synced. #}
{% macro source_table(table) -%}
    {%- set tables = var('source_tables', {}) -%}
    {%- if execute and table not in tables -%}
        {{ exceptions.raise_compiler_error(
            "source_tables has no relation for '" ~ table ~ "'; build these models with jobs.refresh_data"
        ) }}
    {%- endif -%}
    {{ tables.get(table, 'raw.unresolved_source_table') }}
{%- endmacro %}
