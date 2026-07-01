with customers as (

    select * from {{ ref('stg_olist__customers') }}

),

rfm_inputs as (

    select * from {{ ref('int_customers__rfm_inputs') }}

),

latest_customer_attributes as (

    select
        customers.customer_unique_id,
        customers.customer_zip_code_prefix,
        customers.customer_city,
        customers.customer_state
    from customers
    qualify row_number() over (
        partition by customers.customer_unique_id
        order by customers.customer_id desc
    ) = 1

),

rfm_scored as (

    select
        rfm_inputs.*,
        ntile(5) over (order by recency_days desc, customer_unique_id) as recency_score,
        ntile(5) over (order by order_count, customer_unique_id) as frequency_score,
        ntile(5) over (order by monetary_value, customer_unique_id) as monetary_score
    from rfm_inputs

)

select
    rfm_scored.customer_unique_id,
    latest_customer_attributes.customer_zip_code_prefix,
    latest_customer_attributes.customer_city,
    latest_customer_attributes.customer_state,
    rfm_scored.analysis_date,
    rfm_scored.first_purchase_date,
    rfm_scored.last_purchase_date,
    rfm_scored.recency_days,
    rfm_scored.customer_tenure_days,
    rfm_scored.order_count,
    rfm_scored.monetary_value,
    rfm_scored.gross_value,
    rfm_scored.average_order_value,
    rfm_scored.average_review_score,
    rfm_scored.recency_score,
    rfm_scored.frequency_score,
    rfm_scored.monetary_score,
    concat(
        rfm_scored.recency_score,
        rfm_scored.frequency_score,
        rfm_scored.monetary_score
    ) as rfm_score,
    case
        when rfm_scored.recency_score >= 4
            and rfm_scored.frequency_score >= 4
            and rfm_scored.monetary_score >= 4
            then 'champions'
        when rfm_scored.recency_score >= 4
            and rfm_scored.frequency_score >= 3
            then 'loyal_customers'
        when rfm_scored.recency_score >= 3
            and rfm_scored.monetary_score >= 4
            then 'big_spenders'
        when rfm_scored.recency_score <= 2
            and rfm_scored.frequency_score >= 3
            then 'at_risk'
        when rfm_scored.recency_score <= 2
            then 'lost'
        else 'potential_loyalists'
    end as rfm_segment,
    rfm_scored.recency_days > 180 as is_churned
from rfm_scored
left join latest_customer_attributes
    on rfm_scored.customer_unique_id = latest_customer_attributes.customer_unique_id
