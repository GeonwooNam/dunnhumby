-- 목적: 상품 반응과 고객-상품 적합도 결과를 CSV로 내보낸다.
-- 입력: 00~01 단계의 mart 테이블
-- 출력: integration_axis_outputs/*.csv

COPY (
    SELECT *
    FROM mart_product_store_response_detail
    ORDER BY comparison, PRODUCT_ID, STORE_ID
)
TO 'integration_axis_outputs/product_store_response_detail.csv'
(FORMAT CSV, HEADER);

COPY (
    SELECT *
    FROM mart_product_response_profile
    ORDER BY comparison, is_repeated_any_positive DESC,
             eligible_stores DESC, PRODUCT_ID
)
TO 'integration_axis_outputs/product_response_profile.csv'
(FORMAT CSV, HEADER);

COPY (
    SELECT *
    FROM mart_product_response_profile
    WHERE is_repeated_any_positive = 1
    ORDER BY comparison, response_type, eligible_stores DESC,
             positive_spv_store_pct DESC, positive_bpr_store_pct DESC,
             PRODUCT_ID
)
TO 'integration_axis_outputs/product_response_candidates.csv'
(FORMAT CSV, HEADER);

COPY (
    SELECT *
    FROM mart_product_response_support_sensitivity
    ORDER BY comparison, min_weeks
)
TO 'integration_axis_outputs/product_response_support_sensitivity.csv'
(FORMAT CSV, HEADER);

COPY (
    SELECT *
    FROM mart_product_department_response
    ORDER BY comparison, multistore_profiled_products DESC, DEPARTMENT
)
TO 'integration_axis_outputs/product_department_response.csv'
(FORMAT CSV, HEADER);

COPY (
    SELECT *
    FROM mart_product_commodity_response
    ORDER BY comparison, multistore_profiled_products DESC,
             DEPARTMENT, COMMODITY_DESC
)
TO 'integration_axis_outputs/product_commodity_response.csv'
(FORMAT CSV, HEADER);

COPY (
    SELECT *
    FROM mart_product_promotion_candidate_matrix
    ORDER BY candidate_promo_count DESC,
             COALESCE(is_synergy_candidate, 0) DESC,
             PRODUCT_ID
)
TO 'integration_axis_outputs/product_promotion_candidate_matrix.csv'
(FORMAT CSV, HEADER);

COPY (
    SELECT *
    FROM mart_customer_product_fit
    ORDER BY household_key, comparison
)
TO 'integration_axis_outputs/customer_product_fit.csv'
(FORMAT CSV, HEADER);

COPY (
    SELECT *
    FROM mart_customer_product_fit_summary
    ORDER BY comparison
)
TO 'integration_axis_outputs/customer_product_fit_summary.csv'
(FORMAT CSV, HEADER);

COPY (
    SELECT *
    FROM mart_customer_fit_support_sensitivity
    ORDER BY comparison, min_weeks
)
TO 'integration_axis_outputs/customer_fit_support_sensitivity.csv'
(FORMAT CSV, HEADER);

COPY (
    SELECT *
    FROM mart_customer_product_strategy_summary
    ORDER BY comparison, department_relation
)
TO 'integration_axis_outputs/customer_product_strategy_summary.csv'
(FORMAT CSV, HEADER);
