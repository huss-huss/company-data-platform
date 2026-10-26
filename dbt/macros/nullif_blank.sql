{#- Trim a JSON-extracted string and turn empty strings into NULL. -#}
{% macro nullif_blank(expr) -%}
    nullif(trim({{ expr }}), '')
{%- endmacro %}

{#- Lower-case, accent-free, letters/spaces only: the lookup key for country aliases. -#}
{% macro country_alias_key(expr) -%}
    trim(regexp_replace(strip_accents(lower({{ expr }})), '[^a-z ]', '', 'g'))
{%- endmacro %}
