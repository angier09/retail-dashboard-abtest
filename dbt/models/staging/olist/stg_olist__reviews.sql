with source as (

    select * from {{ source('olist', 'reviews') }}

),

numbered as (

    select
        *,
        row_number() over (
            order by
                review_id,
                order_id,
                review_creation_date,
                review_answer_timestamp,
                review_score,
                review_comment_title,
                review_comment_message
        ) as review_row_number
    from source

),

renamed as (

    select
        md5(
            coalesce(cast(review_id as varchar), '')
            || '|'
            || coalesce(cast(order_id as varchar), '')
            || '|'
            || cast(review_row_number as varchar)
        ) as review_event_id,
        cast(review_id as varchar) as review_id,
        cast(order_id as varchar) as order_id,
        cast(review_score as integer) as review_score,
        nullif(trim(cast(review_comment_title as varchar)), '') as review_comment_title,
        nullif(trim(cast(review_comment_message as varchar)), '') as review_comment_message,
        cast(review_creation_date as timestamp) as review_creation_date,
        cast(review_answer_timestamp as timestamp) as review_answer_timestamp
    from numbered

)

select * from renamed
