with order_items as (

    select * from {{ ref('int_order_items__enriched') }}

),

orders as (

    select * from {{ ref('int_orders__enriched') }}

)

select
    order_items.order_item_key as sales_line_item_id,
    order_items.order_id,
    order_items.order_item_id,
    orders.customer_id,
    orders.customer_unique_id,
    order_items.product_id,
    order_items.seller_id,
    orders.order_purchase_timestamp,
    orders.order_purchase_date,
    orders.order_delivered_customer_date,
    orders.customer_city,
    orders.customer_state,
    order_items.product_category_name,
    order_items.product_category_name_english,
    order_items.seller_city,
    order_items.seller_state,
    order_items.item_price,
    order_items.freight_value,
    order_items.item_total_value,
    orders.has_valid_delivery_timing,
    orders.delivery_days,
    orders.delivery_delay_days,
    orders.average_review_score,
    orders.latest_review_score,
    orders.primary_payment_type
from order_items
inner join orders
    on order_items.order_id = orders.order_id
where orders.is_delivered
