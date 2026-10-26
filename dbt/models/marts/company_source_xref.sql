-- Every source record mapped to its golden entity, with the strongest accepted link.
with match_links as (
    select left_record_id as record_id, score from {{ source('resolved', 'pair_scores') }}
    where decision = 'match'
    union all
    select right_record_id, score from {{ source('resolved', 'pair_scores') }}
    where decision = 'match'
),

best_link as (
    select record_id, max(score) as best_match_score
    from match_links
    group by record_id
)

select
    m.record_id,
    m.entity_id,
    r.source,
    r.source_record_id,
    r.company_name                          as source_company_name,
    m.cluster_size,
    b.best_match_score,
    case when m.cluster_size = 1 then 'singleton' else 'matched' end as link_type,
    m.resolved_at
from {{ source('resolved', 'entity_membership') }} as m
inner join {{ ref('int_company_records') }} as r using (record_id)
left join best_link as b using (record_id)
