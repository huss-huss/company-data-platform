-- Registry export: typed and trimmed, one row per registration number (latest fetch wins).
with source as (
    select * from {{ source('raw', 'registry_companies') }}
),

extracted as (
    select
        {{ nullif_blank("payload ->> 'registration_number'") }}  as registration_number,
        {{ nullif_blank("payload ->> 'company_name'") }}         as company_name,
        {{ nullif_blank("payload ->> 'country'") }}              as country_raw,
        {{ nullif_blank("payload ->> 'registered_address'") }}   as street,
        {{ nullif_blank("payload ->> 'city'") }}                 as city,
        lower({{ nullif_blank("payload ->> 'status'") }})        as status,
        coalesce(
            try_strptime(payload ->> 'incorporation_date', '%Y-%m-%d'),
            try_strptime(payload ->> 'incorporation_date', '%d/%m/%Y')
        )::date                                                  as incorporation_date,
        try_cast(payload ->> 'last_updated' as date)::timestamp  as source_updated_at,
        _checksum,
        _fetched_at
    from source
)

select *
from extracted
where registration_number is not null
qualify row_number() over (
    partition by registration_number order by _fetched_at desc, source_updated_at desc
) = 1
