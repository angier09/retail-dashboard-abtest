with source as (

    select * from {{ source('olist', 'payments') }}

),

renamed as (

    select
        cast(order_id as varchar) || '-' || cast(payment_sequential as varchar) as payment_key,
        cast(order_id as varchar) as order_id,
        cast(payment_sequential as integer) as payment_sequential,
        lower(trim(cast(payment_type as varchar))) as payment_type,
        cast(payment_installments as integer) as payment_installments,
        cast(payment_value as decimal(18, 2)) as payment_value
    from source

)

select * from renamed
