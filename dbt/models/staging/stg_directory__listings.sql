-- Directory listings: contact block flattened; free-text "street, city" address split.
with source as (
    select * from {{ source('raw', 'directory_listings') }}
),

extracted as (
    select
        {{ nullif_blank("payload ->> 'listing_id'") }}            as listing_id,
        {{ nullif_blank("payload ->> 'business_name'") }}         as company_name,
        {{ nullif_blank("payload -> 'contact' ->> 'url'") }}      as url,
        {{ nullif_blank("payload -> 'contact' ->> 'email'") }}    as email,
        {{ nullif_blank("payload -> 'contact' ->> 'phone'") }}    as phone,
        {{ nullif_blank("payload ->> 'address'") }}               as address,
        {{ nullif_blank("payload ->> 'country'") }}               as country_raw,
        lower({{ nullif_blank("payload ->> 'category'") }})       as industry,
        try_cast(payload ->> 'scraped_at' as timestamptz)::timestamp as source_updated_at,
        _checksum,
        _fetched_at
    from source
)

select
    * exclude (address),
    address,
    nullif(trim(regexp_extract(address, '^(.*),[^,]*$', 1)), '')   as street,
    nullif(trim(regexp_extract(address, '([^,]*)$', 1)), '')        as city
from extracted
where listing_id is not null
qualify row_number() over (
    partition by listing_id order by source_updated_at desc nulls last, _fetched_at desc
) = 1
