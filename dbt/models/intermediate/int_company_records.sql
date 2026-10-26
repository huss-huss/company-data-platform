-- One row per source record in a single, normalised shape: the input to entity resolution.
-- Name/domain/phone normalisation uses the cdp_* UDFs (Python, src/cdp/normalize.py) so the
-- resolver and the warehouse share one implementation.
with unioned as (
    select
        'registry'               as source,
        registration_number      as source_record_id,
        company_name,
        null::varchar            as website,
        null::varchar            as email,
        null::varchar            as phone,
        street,
        city,
        country_raw,
        registration_number,
        null::integer            as employee_count,
        null::varchar            as industry,
        status,
        incorporation_date,
        source_updated_at,
        _fetched_at
    from {{ ref('stg_registry__companies') }}

    union all

    select
        'api', api_id, company_name, website, null, null, street, city, country_raw,
        null, employee_count, industry, null, null, source_updated_at, _fetched_at
    from {{ ref('stg_api__companies') }}

    union all

    select
        'directory', listing_id, company_name, url, email, phone, street, city, country_raw,
        null, null, industry, null, null, source_updated_at, _fetched_at
    from {{ ref('stg_directory__listings') }}
),

aliases as (
    select alias, country_code from {{ ref('country_aliases') }}
)

select
    u.source || ':' || u.source_record_id                         as record_id,
    u.source,
    u.source_record_id,
    u.company_name,
    cdp_clean_name(u.company_name)                                as name_clean,
    cdp_normalize_name(u.company_name)                            as name_norm,
    cdp_name_key(u.company_name)                                  as name_key,
    cdp_legal_form(u.company_name)                                as legal_form,
    coalesce(cdp_company_domain(u.website), cdp_company_domain(u.email)) as domain,
    cdp_extract_domain(u.website)                                 as website_domain,
    cdp_normalize_phone(u.phone)                                  as phone_norm,
    u.street,
    u.city,
    trim(strip_accents(lower(u.city)))                            as city_norm,
    u.country_raw,
    a.country_code,
    u.registration_number,
    u.employee_count,
    u.industry,
    u.status,
    u.incorporation_date,
    u.source_updated_at,
    u._fetched_at
from unioned as u
left join aliases as a
    on a.alias = {{ country_alias_key('u.country_raw') }}
