with source as (

    select * from {{ source('olist', 'geolocation') }}

),

numbered as (

    select
        *,
        row_number() over (
            order by
                geolocation_zip_code_prefix,
                geolocation_state,
                geolocation_city,
                geolocation_lat,
                geolocation_lng
        ) as geolocation_row_number
    from source

),

renamed as (

    select
        md5(
            coalesce(cast(geolocation_zip_code_prefix as varchar), '')
            || '|'
            || coalesce(cast(geolocation_state as varchar), '')
            || '|'
            || coalesce(cast(geolocation_city as varchar), '')
            || '|'
            || cast(geolocation_row_number as varchar)
        ) as geolocation_event_id,
        cast(geolocation_zip_code_prefix as varchar) as geolocation_zip_code_prefix,
        cast(geolocation_lat as double) as geolocation_lat,
        cast(geolocation_lng as double) as geolocation_lng,
        lower(trim(cast(geolocation_city as varchar))) as geolocation_city,
        upper(trim(cast(geolocation_state as varchar))) as geolocation_state
    from numbered

)

select * from renamed
