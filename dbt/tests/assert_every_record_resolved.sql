-- Every normalised source record must appear in the crosswalk (no silent drops).
select r.record_id
from {{ ref('int_company_records') }} as r
left join {{ ref('company_source_xref') }} as x using (record_id)
where x.record_id is null
