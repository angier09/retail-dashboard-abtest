with source as (

    select * from {{ source('olist', 'customers') }}

),

renamed as (

    select
        cast(customer_id as varchar) as customer_id,
        cast(customer_unique_id as varchar) as customer_unique_id,
        cast(customer_zip_code_prefix as varchar) as customer_zip_code_prefix,
        lower(trim(cast(customer_city as varchar))) as customer_city,
        upper(trim(cast(customer_state as varchar))) as customer_state
    from source

)

select * from renamed
