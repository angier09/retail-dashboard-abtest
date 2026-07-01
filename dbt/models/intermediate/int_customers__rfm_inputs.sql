with delivered_orders as (

    select *
    from {{ ref('int_orders__enriched') }}
    where is_delivered
        and customer_unique_id is not null
        and order_item_revenue > 0

),

analysis_reference as (

    select max(order_purchase_date) as analysis_date
    from delivered_orders

),

customer_orders as (

    select
        customer_unique_id,
        min(order_purchase_date) as first_purchase_date,
        max(order_purchase_date) as last_purchase_date,
        count(distinct order_id) as order_count,
        sum(order_item_revenue) as monetary_value,
        sum(order_gross_value) as gross_value,
        avg(order_item_revenue) as average_order_value,
        avg(average_review_score) as average_review_score
    from delivered_orders
    group by 1

)

select
    customer_orders.customer_unique_id,
    analysis_reference.analysis_date,
    customer_orders.first_purchase_date,
    customer_orders.last_purchase_date,
    date_diff(
        'day',
        customer_orders.last_purchase_date,
        analysis_reference.analysis_date
    ) as recency_days,
    date_diff(
        'day',
        customer_orders.first_purchase_date,
        analysis_reference.analysis_date
    ) as customer_tenure_days,
    customer_orders.order_count,
    customer_orders.monetary_value,
    customer_orders.gross_value,
    customer_orders.average_order_value,
    customer_orders.average_review_score
from customer_orders
cross join analysis_reference
