-- Every scored candidate pair with its features and decision: the explainability trail
-- behind each merge (and each non-merge).
select
    p.pair_id,
    p.left_record_id,
    p.right_record_id,
    l.company_name                          as left_company_name,
    r.company_name                          as right_company_name,
    ml.entity_id                            as left_entity_id,
    mr.entity_id                            as right_entity_id,
    ml.entity_id = mr.entity_id             as same_entity,
    p.blocking_keys,
    p.name_sim,
    p.name_jw,
    p.extra_tokens,
    p.domain_match,
    p.phone_match,
    p.country_match,
    p.city_match,
    p.street_sim,
    p.score,
    p.decision,
    p.reason,
    p.resolved_at
from {{ source('resolved', 'pair_scores') }} as p
inner join {{ ref('int_company_records') }} as l on l.record_id = p.left_record_id
inner join {{ ref('int_company_records') }} as r on r.record_id = p.right_record_id
inner join {{ source('resolved', 'entity_membership') }} as ml on ml.record_id = p.left_record_id
inner join {{ source('resolved', 'entity_membership') }} as mr on mr.record_id = p.right_record_id
