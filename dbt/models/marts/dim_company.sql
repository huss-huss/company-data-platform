-- Golden company records: one row per resolved entity (survivorship done in cdp.resolve).
select
    g.entity_id,
    g.company_name,
    g.name_norm,
    g.registration_number,
    g.status,
    g.incorporation_date,
    g.country_code,
    c.country_name,
    g.street,
    g.city,
    g.domain,
    g.phone,
    g.employee_count,
    g.industry,
    g.record_count,
    g.source_count,
    g.sources,
    g.last_source_update,
    g.field_provenance,
    g.resolved_at
from {{ source('resolved', 'golden_records') }} as g
left join {{ ref('countries') }} as c using (country_code)
