with orders as (

    select * from {{ ref('stg_olist__orders') }}

),

customers as (

    select * from {{ ref('stg_olist__customers') }}

),

payment_summary as (

    select * from {{ ref('int_payments__order_summary') }}

),

review_summary as (

    select * from {{ ref('int_reviews__order_summary') }}

),

order_item_summary as (

    select
        order_id,
        count(*) as order_item_count,
        count(distinct product_id) as distinct_product_count,
        count(distinct seller_id) as distinct_seller_count,
        sum(item_price) as order_item_revenue,
        sum(freight_value) as order_freight_value,
        sum(item_total_value) as order_gross_value
    from {{ ref('int_order_items__enriched') }}
    group by 1

)

select
    orders.order_id,
    orders.customer_id,
    customers.customer_unique_id,
    orders.order_status,
    orders.order_purchase_timestamp,
    cast(orders.order_purchase_timestamp as date) as order_purchase_date,
    orders.order_approved_at,
    orders.order_delivered_carrier_date,
    orders.order_delivered_customer_date,
    orders.order_estimated_delivery_date,
    customers.customer_zip_code_prefix,
    customers.customer_city,
    customers.customer_state,
    coalesce(order_item_summary.order_item_count, 0) as order_item_count,
    coalesce(order_item_summary.distinct_product_count, 0) as distinct_product_count,
    coalesce(order_item_summary.distinct_seller_count, 0) as distinct_seller_count,
    coalesce(order_item_summary.order_item_revenue, 0) as order_item_revenue,
    coalesce(order_item_summary.order_freight_value, 0) as order_freight_value,
    coalesce(order_item_summary.order_gross_value, 0) as order_gross_value,
    payment_summary.payment_count,
    payment_summary.total_payment_value,
    payment_summary.max_payment_installments,
    payment_summary.distinct_payment_type_count,
    payment_summary.primary_payment_type,
    review_summary.review_count,
    review_summary.average_review_score,
    review_summary.minimum_review_score,
    review_summary.maximum_review_score,
    review_summary.latest_review_score,
    review_summary.latest_review_answer_timestamp,
    coalesce(review_summary.has_review_comment, false) as has_review_comment,
    orders.order_status = 'delivered' as is_delivered,
    orders.order_delivered_customer_date is not null
        and orders.order_delivered_customer_date >= orders.order_purchase_timestamp
        as has_valid_delivery_timing,
    case
        when orders.order_delivered_customer_date is not null
            and orders.order_delivered_customer_date >= orders.order_purchase_timestamp
            then date_diff(
                'day',
                cast(orders.order_purchase_timestamp as date),
                cast(orders.order_delivered_customer_date as date)
            )
    end as delivery_days,
    case
        when orders.order_delivered_customer_date is not null
            and orders.order_delivered_customer_date >= orders.order_purchase_timestamp
            then date_diff(
                'day',
                cast(orders.order_estimated_delivery_date as date),
                cast(orders.order_delivered_customer_date as date)
            )
    end as delivery_delay_days
from orders
left join customers
    on orders.customer_id = customers.customer_id
left join order_item_summary
    on orders.order_id = order_item_summary.order_id
left join payment_summary
    on orders.order_id = payment_summary.order_id
left join review_summary
    on orders.order_id = review_summary.order_id
