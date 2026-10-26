-- Singular test: normalised names must never end in a common legal-form token.
select record_id, company_name, name_norm
from {{ ref('int_company_records') }}
where regexp_matches(name_norm, ' (gmbh|ltd|limited|inc|llc|plc|bv|sas|sarl|ab|sl)$')
