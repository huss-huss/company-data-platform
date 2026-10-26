-- Accepted matches must end up in the same entity; reviewed pairs must not have been merged
-- by that pair alone (they may still be connected transitively via stronger edges).
select pair_id, decision, same_entity
from {{ ref('match_audit') }}
where decision = 'match' and not same_entity
