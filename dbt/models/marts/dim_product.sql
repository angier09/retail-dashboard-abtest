with products as (

    select * from {{ ref('stg_olist__products') }}

),

translations as (

    select * from {{ ref('stg_olist__product_category_translations') }}

),

sales_rollup as (

    select
        product_id,
        count(*) as delivered_item_count,
        count(distinct order_id) as delivered_order_count,
        count(distinct customer_unique_id) as delivered_customer_count,
        sum(item_price) as delivered_item_revenue,
        sum(freight_value) as delivered_freight_value,
        sum(item_total_value) as delivered_gross_value,
        avg(item_price) as average_item_price
    from {{ ref('fct_sales') }}
    group by 1

)

select
    products.product_id,
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
    coalesce(sales_rollup.delivered_item_count, 0) as delivered_item_count,
    coalesce(sales_rollup.delivered_order_count, 0) as delivered_order_count,
    coalesce(sales_rollup.delivered_customer_count, 0) as delivered_customer_count,
    coalesce(sales_rollup.delivered_item_revenue, 0) as delivered_item_revenue,
    coalesce(sales_rollup.delivered_freight_value, 0) as delivered_freight_value,
    coalesce(sales_rollup.delivered_gross_value, 0) as delivered_gross_value,
    sales_rollup.average_item_price
from products
left join translations
    on products.product_category_name = translations.product_category_name
left join sales_rollup
    on products.product_id = sales_rollup.product_id
