-- 목적: 동일 상품-점포 내부 프로모션 차이를 상품 수준의 반복 반응 프로필로 집계한다.
-- 입력: product_axis.work_pair_group_means, source.product
-- 출력: work_product_store_state, mart_product_store_response_detail,
--       mart_product_response_profile, mart_product_response_support_sensitivity,
--       mart_product_department_response
-- 주 규칙: 각 비교 상태가 3주 이상 관측된 상품-점포만 상품 프로필에 사용한다.
--          3개 이상 점포와 60% 이상 동일 방향을 반복 반응 후보의 최소 지지도로 둔다.

CREATE OR REPLACE TABLE work_product_store_state AS
SELECT
    PRODUCT_ID,
    STORE_ID,
    MAX(observed_weeks) FILTER (WHERE promo_group = 'none') AS none_weeks,
    MAX(observed_weeks) FILTER (WHERE promo_group = 'display_only')
        AS display_only_weeks,
    MAX(observed_weeks) FILTER (WHERE promo_group = 'mailer_only')
        AS mailer_only_weeks,
    MAX(observed_weeks) FILTER (WHERE promo_group = 'both') AS both_weeks,
    MAX(avg_sales_per_visitor) FILTER (WHERE promo_group = 'none') AS none_spv,
    MAX(avg_sales_per_visitor) FILTER (WHERE promo_group = 'display_only')
        AS display_only_spv,
    MAX(avg_sales_per_visitor) FILTER (WHERE promo_group = 'mailer_only')
        AS mailer_only_spv,
    MAX(avg_sales_per_visitor) FILTER (WHERE promo_group = 'both') AS both_spv,
    MAX(avg_buyer_penetration_rate) FILTER (WHERE promo_group = 'none')
        AS none_bpr,
    MAX(avg_buyer_penetration_rate) FILTER (WHERE promo_group = 'display_only')
        AS display_only_bpr,
    MAX(avg_buyer_penetration_rate) FILTER (WHERE promo_group = 'mailer_only')
        AS mailer_only_bpr,
    MAX(avg_buyer_penetration_rate) FILTER (WHERE promo_group = 'both')
        AS both_bpr,
    MAX(avg_basket_share_rate) FILTER (WHERE promo_group = 'none')
        AS none_basket_share,
    MAX(avg_basket_share_rate) FILTER (WHERE promo_group = 'display_only')
        AS display_only_basket_share,
    MAX(avg_basket_share_rate) FILTER (WHERE promo_group = 'mailer_only')
        AS mailer_only_basket_share,
    MAX(avg_basket_share_rate) FILTER (WHERE promo_group = 'both')
        AS both_basket_share,
    MAX(avg_category_sales_share_rate) FILTER (WHERE promo_group = 'none')
        AS none_category_share,
    MAX(avg_category_sales_share_rate) FILTER (WHERE promo_group = 'display_only')
        AS display_only_category_share,
    MAX(avg_category_sales_share_rate) FILTER (WHERE promo_group = 'mailer_only')
        AS mailer_only_category_share,
    MAX(avg_category_sales_share_rate) FILTER (WHERE promo_group = 'both')
        AS both_category_share
FROM product_axis.work_pair_group_means
GROUP BY 1, 2;

CREATE OR REPLACE TABLE mart_product_store_response_detail AS
WITH comparisons AS (
    SELECT
        PRODUCT_ID,
        STORE_ID,
        'display_only_vs_none' AS comparison,
        'none' AS reference_state,
        'display_only' AS comparison_state,
        none_weeks AS reference_weeks,
        display_only_weeks AS comparison_weeks,
        LEAST(none_weeks, display_only_weeks) AS min_state_weeks,
        none_spv AS reference_spv,
        display_only_spv AS comparison_spv,
        none_bpr AS reference_bpr,
        display_only_bpr AS comparison_bpr,
        none_basket_share AS reference_basket_share,
        display_only_basket_share AS comparison_basket_share,
        none_category_share AS reference_category_share,
        display_only_category_share AS comparison_category_share
    FROM work_product_store_state
    WHERE none_weeks IS NOT NULL AND display_only_weeks IS NOT NULL

    UNION ALL

    SELECT
        PRODUCT_ID,
        STORE_ID,
        'mailer_only_vs_none',
        'none',
        'mailer_only',
        none_weeks,
        mailer_only_weeks,
        LEAST(none_weeks, mailer_only_weeks),
        none_spv,
        mailer_only_spv,
        none_bpr,
        mailer_only_bpr,
        none_basket_share,
        mailer_only_basket_share,
        none_category_share,
        mailer_only_category_share
    FROM work_product_store_state
    WHERE none_weeks IS NOT NULL AND mailer_only_weeks IS NOT NULL

    UNION ALL

    SELECT
        PRODUCT_ID,
        STORE_ID,
        'both_vs_none',
        'none',
        'both',
        none_weeks,
        both_weeks,
        LEAST(none_weeks, both_weeks),
        none_spv,
        both_spv,
        none_bpr,
        both_bpr,
        none_basket_share,
        both_basket_share,
        none_category_share,
        both_category_share
    FROM work_product_store_state
    WHERE none_weeks IS NOT NULL AND both_weeks IS NOT NULL

    UNION ALL

    SELECT
        PRODUCT_ID,
        STORE_ID,
        'both_vs_additive',
        'display+mailer-none',
        'both',
        LEAST(none_weeks, display_only_weeks, mailer_only_weeks),
        both_weeks,
        LEAST(none_weeks, display_only_weeks, mailer_only_weeks, both_weeks),
        display_only_spv + mailer_only_spv - none_spv,
        both_spv,
        display_only_bpr + mailer_only_bpr - none_bpr,
        both_bpr,
        display_only_basket_share + mailer_only_basket_share
            - none_basket_share,
        both_basket_share,
        display_only_category_share + mailer_only_category_share
            - none_category_share,
        both_category_share
    FROM work_product_store_state
    WHERE none_weeks IS NOT NULL
      AND display_only_weeks IS NOT NULL
      AND mailer_only_weeks IS NOT NULL
      AND both_weeks IS NOT NULL
)
SELECT
    *,
    comparison_spv - reference_spv AS spv_difference,
    comparison_bpr - reference_bpr AS bpr_difference,
    comparison_basket_share - reference_basket_share
        AS basket_share_difference,
    comparison_category_share - reference_category_share
        AS category_share_difference,
    CASE WHEN comparison_spv > reference_spv THEN 1 ELSE 0 END
        AS is_positive_spv,
    CASE WHEN comparison_bpr > reference_bpr THEN 1 ELSE 0 END
        AS is_positive_bpr
FROM comparisons;

CREATE OR REPLACE TABLE mart_product_response_profile AS
WITH product_summary AS (
    SELECT
        d.PRODUCT_ID,
        d.comparison,
        COUNT(*) AS eligible_stores,
        SUM(d.reference_weeks) AS reference_weeks,
        SUM(d.comparison_weeks) AS comparison_weeks,
        AVG(d.reference_spv) AS avg_reference_spv,
        AVG(d.comparison_spv) AS avg_comparison_spv,
        AVG(d.spv_difference) AS mean_spv_difference,
        MEDIAN(d.spv_difference) AS median_spv_difference,
        100.0 * AVG(CASE WHEN d.is_positive_spv = 1 THEN 1.0 ELSE 0.0 END)
            AS positive_spv_store_pct,
        AVG(d.bpr_difference) AS mean_bpr_difference,
        MEDIAN(d.bpr_difference) AS median_bpr_difference,
        100.0 * AVG(CASE WHEN d.is_positive_bpr = 1 THEN 1.0 ELSE 0.0 END)
            AS positive_bpr_store_pct,
        AVG(d.basket_share_difference) AS mean_basket_share_difference,
        AVG(d.category_share_difference) AS mean_category_share_difference,
        COUNT(*) FILTER (WHERE d.reference_spv = 0) AS zero_reference_stores
    FROM mart_product_store_response_detail AS d
    WHERE d.min_state_weeks >= 3
    GROUP BY 1, 2
), classified AS (
    SELECT
        s.*,
        CASE
            WHEN eligible_stores >= 3 THEN 'multi_store_repeated'
            WHEN eligible_stores = 2 THEN 'two_store_limited'
            ELSE 'single_store_limited'
        END AS support_tier,
        CASE
            WHEN eligible_stores >= 3
             AND median_spv_difference > 0
             AND positive_spv_store_pct >= 60
            THEN 1 ELSE 0
        END AS is_repeated_sales_positive,
        CASE
            WHEN eligible_stores >= 3
             AND median_bpr_difference > 0
             AND positive_bpr_store_pct >= 60
            THEN 1 ELSE 0
        END AS is_repeated_penetration_positive
    FROM product_summary AS s
)
SELECT
    c.PRODUCT_ID,
    p.MANUFACTURER,
    p.DEPARTMENT,
    p.BRAND,
    p.COMMODITY_DESC,
    p.SUB_COMMODITY_DESC,
    p.CURR_SIZE_OF_PRODUCT,
    c.* EXCLUDE (PRODUCT_ID),
    CASE
        WHEN is_repeated_sales_positive = 1
         AND is_repeated_penetration_positive = 1
            THEN 'sales_and_penetration_positive'
        WHEN is_repeated_sales_positive = 1
            THEN 'sales_positive_only'
        WHEN is_repeated_penetration_positive = 1
            THEN 'penetration_positive_only'
        WHEN support_tier <> 'multi_store_repeated'
            THEN 'insufficient_multistore_support'
        ELSE 'mixed_or_nonpositive'
    END AS response_type,
    CASE
        WHEN is_repeated_sales_positive = 1
          OR is_repeated_penetration_positive = 1
        THEN 1 ELSE 0
    END AS is_repeated_any_positive,
    CASE
        WHEN avg_reference_spv > 0
        THEN 100.0 * (avg_comparison_spv / avg_reference_spv - 1)
    END AS product_level_spv_lift_pct
FROM classified AS c
LEFT JOIN source.product AS p USING (PRODUCT_ID);

CREATE OR REPLACE TABLE mart_product_response_support_sensitivity AS
WITH thresholds AS (
    SELECT min_weeks FROM range(1, 6) AS t(min_weeks)
), eligible AS (
    SELECT t.min_weeks, d.*
    FROM thresholds AS t
    JOIN mart_product_store_response_detail AS d
      ON d.min_state_weeks >= t.min_weeks
), product_summary AS (
    SELECT
        min_weeks,
        comparison,
        PRODUCT_ID,
        COUNT(*) AS eligible_stores,
        MEDIAN(spv_difference) AS median_spv_difference,
        MEDIAN(bpr_difference) AS median_bpr_difference,
        100.0 * AVG(CASE WHEN is_positive_spv = 1 THEN 1.0 ELSE 0.0 END)
            AS positive_spv_store_pct,
        100.0 * AVG(CASE WHEN is_positive_bpr = 1 THEN 1.0 ELSE 0.0 END)
            AS positive_bpr_store_pct
    FROM eligible
    GROUP BY 1, 2, 3
), classified AS (
    SELECT
        *,
        CASE
            WHEN eligible_stores >= 3
             AND median_spv_difference > 0
             AND positive_spv_store_pct >= 60
            THEN 1 ELSE 0
        END AS sales_candidate,
        CASE
            WHEN eligible_stores >= 3
             AND median_bpr_difference > 0
             AND positive_bpr_store_pct >= 60
            THEN 1 ELSE 0
        END AS penetration_candidate
    FROM product_summary
), pair_counts AS (
    SELECT
        t.min_weeks,
        d.comparison,
        COUNT(*) AS eligible_product_store_pairs
    FROM thresholds AS t
    JOIN mart_product_store_response_detail AS d
      ON d.min_state_weeks >= t.min_weeks
    GROUP BY 1, 2
)
SELECT
    c.min_weeks,
    c.comparison,
    p.eligible_product_store_pairs,
    COUNT(*) AS profiled_products,
    COUNT(*) FILTER (WHERE c.eligible_stores >= 3) AS multistore_products,
    SUM(c.sales_candidate) AS repeated_sales_positive_products,
    SUM(c.penetration_candidate) AS repeated_penetration_positive_products,
    COUNT(*) FILTER (
        WHERE c.sales_candidate = 1 OR c.penetration_candidate = 1
    ) AS repeated_any_positive_products
FROM classified AS c
JOIN pair_counts AS p USING (min_weeks, comparison)
GROUP BY 1, 2, 3
ORDER BY 2, 1;

CREATE OR REPLACE TABLE mart_product_department_response AS
SELECT
    comparison,
    DEPARTMENT,
    COUNT(*) AS multistore_profiled_products,
    SUM(is_repeated_sales_positive) AS repeated_sales_positive_products,
    SUM(is_repeated_penetration_positive)
        AS repeated_penetration_positive_products,
    SUM(is_repeated_any_positive) AS repeated_any_positive_products,
    100.0 * AVG(CASE WHEN is_repeated_any_positive = 1 THEN 1.0 ELSE 0.0 END)
        AS repeated_any_positive_product_pct,
    MEDIAN(median_spv_difference) AS median_product_spv_difference,
    MEDIAN(median_bpr_difference) AS median_product_bpr_difference
FROM mart_product_response_profile
WHERE support_tier = 'multi_store_repeated'
GROUP BY 1, 2
ORDER BY 1, multistore_profiled_products DESC, 2;

CREATE OR REPLACE TABLE mart_product_commodity_response AS
SELECT
    comparison,
    DEPARTMENT,
    COMMODITY_DESC,
    COUNT(*) AS multistore_profiled_products,
    SUM(is_repeated_sales_positive) AS repeated_sales_positive_products,
    SUM(is_repeated_penetration_positive)
        AS repeated_penetration_positive_products,
    SUM(is_repeated_any_positive) AS repeated_any_positive_products,
    100.0 * AVG(CASE WHEN is_repeated_any_positive = 1 THEN 1.0 ELSE 0.0 END)
        AS repeated_any_positive_product_pct,
    MEDIAN(median_spv_difference) AS median_product_spv_difference,
    MEDIAN(median_bpr_difference) AS median_product_bpr_difference
FROM mart_product_response_profile
WHERE support_tier = 'multi_store_repeated'
GROUP BY 1, 2, 3
ORDER BY 1, multistore_profiled_products DESC, 2, 3;

CREATE OR REPLACE TABLE mart_product_promotion_candidate_matrix AS
SELECT
    PRODUCT_ID,
    MAX(MANUFACTURER) AS MANUFACTURER,
    MAX(DEPARTMENT) AS DEPARTMENT,
    MAX(BRAND) AS BRAND,
    MAX(COMMODITY_DESC) AS COMMODITY_DESC,
    MAX(SUB_COMMODITY_DESC) AS SUB_COMMODITY_DESC,
    MAX(CURR_SIZE_OF_PRODUCT) AS CURR_SIZE_OF_PRODUCT,
    MAX(eligible_stores) FILTER (WHERE comparison = 'display_only_vs_none')
        AS display_eligible_stores,
    MAX(is_repeated_any_positive)
        FILTER (WHERE comparison = 'display_only_vs_none')
        AS is_display_candidate,
    MAX(response_type) FILTER (WHERE comparison = 'display_only_vs_none')
        AS display_response_type,
    MAX(eligible_stores) FILTER (WHERE comparison = 'mailer_only_vs_none')
        AS mailer_eligible_stores,
    MAX(is_repeated_any_positive)
        FILTER (WHERE comparison = 'mailer_only_vs_none')
        AS is_mailer_candidate,
    MAX(response_type) FILTER (WHERE comparison = 'mailer_only_vs_none')
        AS mailer_response_type,
    MAX(eligible_stores) FILTER (WHERE comparison = 'both_vs_none')
        AS both_eligible_stores,
    MAX(is_repeated_any_positive) FILTER (WHERE comparison = 'both_vs_none')
        AS is_both_candidate,
    MAX(response_type) FILTER (WHERE comparison = 'both_vs_none')
        AS both_response_type,
    MAX(eligible_stores) FILTER (WHERE comparison = 'both_vs_additive')
        AS synergy_eligible_stores,
    MAX(is_repeated_any_positive) FILTER (WHERE comparison = 'both_vs_additive')
        AS is_synergy_candidate,
    MAX(response_type) FILTER (WHERE comparison = 'both_vs_additive')
        AS synergy_response_type,
    COALESCE(MAX(is_repeated_any_positive)
        FILTER (WHERE comparison = 'display_only_vs_none'), 0)
      + COALESCE(MAX(is_repeated_any_positive)
        FILTER (WHERE comparison = 'mailer_only_vs_none'), 0)
      + COALESCE(MAX(is_repeated_any_positive)
        FILTER (WHERE comparison = 'both_vs_none'), 0)
        AS candidate_promo_count
FROM mart_product_response_profile
GROUP BY PRODUCT_ID
HAVING candidate_promo_count > 0
    OR COALESCE(MAX(is_repeated_any_positive)
        FILTER (WHERE comparison = 'both_vs_additive'), 0) = 1
ORDER BY candidate_promo_count DESC,
         COALESCE(is_synergy_candidate, 0) DESC,
         PRODUCT_ID;
