with reviews as (

    select * from {{ ref('stg_olist__reviews') }}

),

latest_reviews as (

    select
        order_id,
        review_score as latest_review_score,
        review_answer_timestamp as latest_review_answer_timestamp
    from reviews
    qualify row_number() over (
        partition by order_id
        order by review_answer_timestamp desc, review_creation_date desc, review_event_id
    ) = 1

),

review_summary as (

    select
        order_id,
        count(*) as review_count,
        avg(review_score) as average_review_score,
        min(review_score) as minimum_review_score,
        max(review_score) as maximum_review_score,
        max(case when review_comment_message is not null then 1 else 0 end) as has_review_comment
    from reviews
    group by 1

)

select
    review_summary.order_id,
    review_summary.review_count,
    review_summary.average_review_score,
    review_summary.minimum_review_score,
    review_summary.maximum_review_score,
    latest_reviews.latest_review_score,
    latest_reviews.latest_review_answer_timestamp,
    cast(review_summary.has_review_comment as boolean) as has_review_comment
from review_summary
left join latest_reviews
    on review_summary.order_id = latest_reviews.order_id
