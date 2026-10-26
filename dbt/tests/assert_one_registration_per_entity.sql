-- Cannot-link constraint: two different registry registrations never share an entity.
select x.entity_id, count(distinct r.registration_number) as registrations
from {{ ref('company_source_xref') }} as x
inner join {{ ref('int_company_records') }} as r using (record_id)
where r.source = 'registry'
group by x.entity_id
having count(distinct r.registration_number) > 1
