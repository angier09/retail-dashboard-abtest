select *
from {{ ref('fct_orders') }}
where order_item_revenue < 0
    or order_freight_value < 0
    or order_gross_value < 0
    or total_payment_value < 0

union all

select
    order_id,
    null as customer_id,
    customer_unique_id,
    null as order_status,
    order_purchase_timestamp,
    order_purchase_date,
    null as order_approved_at,
    null as order_delivered_carrier_date,
    order_delivered_customer_date,
    null as order_estimated_delivery_date,
    null as customer_zip_code_prefix,
    customer_city,
    customer_state,
    null as order_item_count,
    null as distinct_product_count,
    null as distinct_seller_count,
    item_price as order_item_revenue,
    freight_value as order_freight_value,
    item_total_value as order_gross_value,
    null as payment_count,
    null as total_payment_value,
    null as max_payment_installments,
    null as distinct_payment_type_count,
    primary_payment_type,
    null as review_count,
    average_review_score,
    latest_review_score,
    null as has_review_comment,
    true as is_delivered,
    has_valid_delivery_timing,
    delivery_days,
    delivery_delay_days
from {{ ref('fct_sales') }}
where item_price < 0
    or freight_value < 0
    or item_total_value < 0
