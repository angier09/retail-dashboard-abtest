with geolocation as (

    select * from {{ ref('stg_olist__geolocation') }}

),

city_counts as (

    select
        geolocation_zip_code_prefix,
        geolocation_state,
        geolocation_city,
        count(*) as city_observation_count
    from geolocation
    group by 1, 2, 3

),

primary_city as (

    select
        geolocation_zip_code_prefix,
        geolocation_state,
        geolocation_city as primary_city
    from city_counts
    qualify row_number() over (
        partition by geolocation_zip_code_prefix, geolocation_state
        order by city_observation_count desc, geolocation_city
    ) = 1

),

zip_summary as (

    select
        geolocation_zip_code_prefix,
        geolocation_state,
        count(*) as geolocation_observation_count,
        avg(geolocation_lat) as average_latitude,
        avg(geolocation_lng) as average_longitude
    from geolocation
    group by 1, 2

)

select
    zip_summary.geolocation_zip_code_prefix,
    zip_summary.geolocation_state,
    primary_city.primary_city,
    zip_summary.geolocation_observation_count,
    zip_summary.average_latitude,
    zip_summary.average_longitude
from zip_summary
left join primary_city
    on zip_summary.geolocation_zip_code_prefix = primary_city.geolocation_zip_code_prefix
    and zip_summary.geolocation_state = primary_city.geolocation_state
