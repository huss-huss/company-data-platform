-- Company API: nested `hq` flattened, numeric/timestamp fields typed, latest version per id.
with source as (
    select * from {{ source('raw', 'api_companies') }}
),

extracted as (
    select
        {{ nullif_blank("payload ->> 'id'") }}                     as api_id,
        {{ nullif_blank("payload ->> 'name'") }}                   as company_name,
        {{ nullif_blank("payload ->> 'website'") }}                as website,
        {{ nullif_blank("payload -> 'hq' ->> 'street'") }}         as street,
        {{ nullif_blank("payload -> 'hq' ->> 'city'") }}           as city,
        upper({{ nullif_blank("payload -> 'hq' ->> 'country_code'") }}) as country_raw,
        try_cast(payload ->> 'employee_count' as integer)          as employee_count,
        lower({{ nullif_blank("payload ->> 'industry'") }})        as industry,
        try_cast(payload ->> 'updated_at' as timestamptz)::timestamp as source_updated_at,
        _checksum,
        _fetched_at
    from source
)

select *
from extracted
where api_id is not null
qualify row_number() over (
    partition by api_id order by source_updated_at desc nulls last, _fetched_at desc
) = 1
