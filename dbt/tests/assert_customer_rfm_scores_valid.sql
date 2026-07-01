select *
from {{ ref('dim_customer') }}
where recency_score not between 1 and 5
    or frequency_score not between 1 and 5
    or monetary_score not between 1 and 5
    or recency_days < 0
    or order_count <= 0
    or monetary_value <= 0
