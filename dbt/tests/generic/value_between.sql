{# Fails every row whose value is NULL or outside the half-open range [min_value, max_value). #}
{% test value_between(model, column_name, min_value, max_value) %}
select {{ column_name }}
from {{ model }}
where {{ column_name }} is null
   or not ({{ column_name }} >= {{ min_value }} and {{ column_name }} < {{ max_value }})
{% endtest %}
