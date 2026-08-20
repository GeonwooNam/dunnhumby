-- 목적: 상품군별 프로모션 후보 분석 결과를 소규모 CSV로 내보낸다.
-- 입력: 09_category_promotion_priority.sql의 mart 테이블
-- 출력: product_axis_outputs/category_promotion_*.csv

COPY (
    SELECT *
    FROM mart_category_promotion_response_sensitivity
    ORDER BY min_weeks, COMMODITY_DESC, comparison
)
TO 'product_axis_outputs/category_promotion_response_sensitivity.csv'
(FORMAT CSV, HEADER);

COPY (
    SELECT *
    FROM mart_category_promotion_main
    ORDER BY COMMODITY_DESC,
        CASE comparison
            WHEN 'display_only_vs_none' THEN 1
            WHEN 'mailer_only_vs_none' THEN 2
            WHEN 'both_vs_none' THEN 3
            ELSE 4
        END
)
TO 'product_axis_outputs/category_promotion_main.csv'
(FORMAT CSV, HEADER);

COPY (
    SELECT *
    FROM mart_category_promotion_matrix
    ORDER BY candidate_promo_count DESC, COMMODITY_DESC
)
TO 'product_axis_outputs/category_promotion_matrix.csv'
(FORMAT CSV, HEADER);
