with payments as (

    select * from {{ ref('stg_olist__payments') }}

),

payment_type_rollup as (

    select
        order_id,
        payment_type,
        count(*) as payment_type_row_count,
        sum(payment_value) as payment_type_value
    from payments
    group by 1, 2

),

primary_payment_type as (

    select
        order_id,
        payment_type as primary_payment_type
    from payment_type_rollup
    qualify row_number() over (
        partition by order_id
        order by payment_type_value desc, payment_type_row_count desc, payment_type
    ) = 1

),

payment_summary as (

    select
        payments.order_id,
        count(*) as payment_count,
        sum(payments.payment_value) as total_payment_value,
        max(payments.payment_installments) as max_payment_installments,
        count(distinct payments.payment_type) as distinct_payment_type_count
    from payments
    group by 1

)

select
    payment_summary.order_id,
    payment_summary.payment_count,
    payment_summary.total_payment_value,
    payment_summary.max_payment_installments,
    payment_summary.distinct_payment_type_count,
    primary_payment_type.primary_payment_type
from payment_summary
left join primary_payment_type
    on payment_summary.order_id = primary_payment_type.order_id
