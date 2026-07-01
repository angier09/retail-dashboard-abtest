with order_items as (

    select * from {{ ref('stg_olist__order_items') }}

),

products as (

    select * from {{ ref('stg_olist__products') }}

),

translations as (

    select * from {{ ref('stg_olist__product_category_translations') }}

),

sellers as (

    select * from {{ ref('stg_olist__sellers') }}

)

select
    order_items.order_item_key,
    order_items.order_id,
    order_items.order_item_id,
    order_items.product_id,
    order_items.seller_id,
    order_items.shipping_limit_date,
    order_items.item_price,
    order_items.freight_value,
    order_items.item_price + order_items.freight_value as item_total_value,
    products.product_category_name,
    coalesce(
        translations.product_category_name_english,
        products.product_category_name,
        'unknown'
    ) as product_category_name_english,
    products.product_name_length,
    products.product_description_length,
    products.product_photos_qty,
    products.product_weight_g,
    products.product_length_cm,
    products.product_height_cm,
    products.product_width_cm,
    sellers.seller_zip_code_prefix,
    sellers.seller_city,
    sellers.seller_state
from order_items
left join products
    on order_items.product_id = products.product_id
left join translations
    on products.product_category_name = translations.product_category_name
left join sellers
    on order_items.seller_id = sellers.seller_id
