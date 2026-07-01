with delivered_orders as (

    select *
    from {{ ref('fct_orders') }}
    where is_delivered
        and order_item_revenue > 0

)

select
    order_purchase_date,
    count(distinct order_id) as delivered_order_count,
    count(distinct customer_unique_id) as customer_count,
    sum(order_item_count) as item_count,
    sum(order_item_revenue) as item_revenue,
    sum(order_freight_value) as freight_revenue,
    sum(order_gross_value) as gross_revenue,
    avg(order_item_revenue) as average_order_revenue,
    avg(delivery_days) as average_delivery_days,
    avg(average_review_score) as average_review_score
from delivered_orders
group by 1
