with source as (

    select * from {{ source('olist', 'product_category_translations') }}

),

renamed as (

    select
        lower(trim(cast(product_category_name as varchar))) as product_category_name,
        lower(trim(cast(product_category_name_english as varchar))) as product_category_name_english
    from source

)

select * from renamed
