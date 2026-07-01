with sellers as (

    select * from {{ ref('stg_olist__sellers') }}

),

sales_rollup as (

    select
        seller_id,
        count(*) as delivered_item_count,
        count(distinct order_id) as delivered_order_count,
        count(distinct customer_unique_id) as delivered_customer_count,
        sum(item_price) as delivered_item_revenue,
        sum(freight_value) as delivered_freight_value,
        sum(item_total_value) as delivered_gross_value,
        avg(item_price) as average_item_price,
        avg(delivery_days) as average_delivery_days,
        avg(latest_review_score) as average_latest_review_score
    from {{ ref('fct_sales') }}
    group by 1

)

select
    sellers.seller_id,
    sellers.seller_zip_code_prefix,
    sellers.seller_city,
    sellers.seller_state,
    coalesce(sales_rollup.delivered_item_count, 0) as delivered_item_count,
    coalesce(sales_rollup.delivered_order_count, 0) as delivered_order_count,
    coalesce(sales_rollup.delivered_customer_count, 0) as delivered_customer_count,
    coalesce(sales_rollup.delivered_item_revenue, 0) as delivered_item_revenue,
    coalesce(sales_rollup.delivered_freight_value, 0) as delivered_freight_value,
    coalesce(sales_rollup.delivered_gross_value, 0) as delivered_gross_value,
    sales_rollup.average_item_price,
    sales_rollup.average_delivery_days,
    sales_rollup.average_latest_review_score
from sellers
left join sales_rollup
    on sellers.seller_id = sales_rollup.seller_id
