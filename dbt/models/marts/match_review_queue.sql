-- Uncertain pairs for a data steward: never auto-merged. Highest scores first.
select
    pair_id,
    left_record_id,
    right_record_id,
    left_company_name,
    right_company_name,
    score,
    reason,
    resolved_at
from {{ ref('match_audit') }}
where decision = 'review'
