select *
from {{ ref('fct_orders') }}
where delivery_days < 0
    or (
        has_valid_delivery_timing
        and order_delivered_customer_date is null
    )
