with source as (

    select * from {{ source('olist', 'products') }}

),

renamed as (

    select
        cast(product_id as varchar) as product_id,
        lower(trim(cast(product_category_name as varchar))) as product_category_name,
        cast(product_name_lenght as integer) as product_name_length,
        cast(product_description_lenght as integer) as product_description_length,
        cast(product_photos_qty as integer) as product_photos_qty,
        cast(product_weight_g as integer) as product_weight_g,
        cast(product_length_cm as integer) as product_length_cm,
        cast(product_height_cm as integer) as product_height_cm,
        cast(product_width_cm as integer) as product_width_cm
    from source

)

select * from renamed
